"""Local playlist library — playlists that live in SongMirror itself, independent
of any one connected service. Clone one from a provider, build one by hand, or
import a SongMirror backup; then compare it against a live provider playlist and
push (resync) it back out. Reuses the one-way sync engine's diff/safety
primitives (engine.matching.compute_diff / protect_removals) the same way the
isolated transfer copy engine does, instead of the N-way reconcile baseline
system — this stays a separate, explicit, user-triggered workflow.
"""

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from ..engine import logs, spotify, spotify_cookie
from ..engine.config import parse_args, spotify_write_backend
from ..engine.matching import compute_diff, protect_removals
from ..engine.runner import load_cache, save_cache
from ..engine.targets import build_one
from ..engine.targets.base import TargetAuthError, TargetTransientError, _split_add_results
from .playlist_exports import BACKUP_KIND, SCHEMA_VERSION, parse_xml_backup
from .playlists import PlaylistService
from .settings import _open_private


class LocalLibraryError(RuntimeError):
    status_code = 502


class LocalPlaylistNotFoundError(LocalLibraryError):
    status_code = 404


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id():
    return uuid.uuid4().hex[:8]


def _local_track_from_row(row, *, provider_id=None, keep_occurrence=False):
    """Build a local track dict from a provider detail row or a backup track
    row — both share the same field names (services/playlists.py's
    _normalize_tracks and playlist_exports.py's _TRACK_FIELDS)."""
    links = {}
    if provider_id and row.get("id"):
        links[provider_id] = {
            "id": str(row["id"]),
            "occurrence_id": str(row.get("occurrence_id") or "") if keep_occurrence else "",
        }
    return {
        "id": _new_id(),
        "name": str(row.get("name") or "Unknown track"),
        "artist": str(row.get("artist") or ""),
        "album": str(row.get("album") or ""),
        "isrc": str(row.get("isrc") or ""),
        "duration_ms": row.get("duration_ms"),
        "image": str(row.get("image") or ""),
        "added_at": str(row.get("added_at") or ""),
        "links": links,
    }


def _as_source_track(local_track):
    """Adapt a local track dict into the shape compute_diff/resolve expect for
    the source side (Spotify-shaped: artists is a list)."""
    artist = local_track.get("artist") or ""
    return {
        "id": local_track["id"],
        "name": local_track.get("name") or "",
        "artists": [artist] if artist else [],
        "isrc": local_track.get("isrc") or "",
        "duration_ms": local_track.get("duration_ms"),
        "added_at": local_track.get("added_at") or "",
        "image": local_track.get("image") or "",
    }


def _with_artist(track):
    """Spotify's raw playlist-track dict (all three read paths: official API,
    cookie, and web-scraper fallback) carries only an "artists" list, no
    singular "artist" string — unlike every other target. compute_diff() and
    the emit/pull code below index "artist" directly, so patch it in without
    disturbing any other raw field track_id()/remove() still need."""
    if track.get("artist"):
        return track
    return {**track, "artist": ", ".join(a for a in track.get("artists") or [] if a)}


def _expected_ids(local_tracks, provider_id):
    expected = {}
    for t in local_tracks:
        known = (t.get("links") or {}).get(provider_id, {}).get("id")
        if known:
            expected[t["id"]] = {str(known)}
    return expected


def _diff_track_summary(track, *, track_id):
    artist = track.get("artist")
    if artist is None:
        artist = ", ".join(track.get("artists") or [])
    return {
        "id": str(track_id or ""),
        "name": track.get("name") or "",
        "artist": artist,
        "album": track.get("album") or "",
        "duration_ms": track.get("duration_ms"),
        "added_at": track.get("added_at") or "",
        "image": track.get("image") or "",
    }


@dataclass
class LocalPlaylist:
    name: str
    description: str = ""
    image: str = ""
    tracks: list = field(default_factory=list)         # list[dict], see _local_track_from_row
    links: dict = field(default_factory=dict)           # provider_id -> playlist_id (resync target)
    created_at: str = ""
    updated_at: str = ""
    id: str = ""


class LocalPlaylistStore:
    """User-curated playlists persisted to data/local_playlists.json (owner-only,
    alongside the other data-dir state — see LinkStore in services/playlists.py)."""

    def __init__(self, dir="data"):
        self._path = Path(dir) / "local_playlists.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def list(self):
        try:
            with open(self._path, encoding="utf-8") as f:
                return [LocalPlaylist(**d) for d in json.load(f)]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def get(self, playlist_id):
        return next((p for p in self.list() if p.id == playlist_id), None)

    def upsert(self, playlist):
        now = _utc_now()
        if not playlist.id:
            playlist.id = _new_id()
            playlist.created_at = playlist.created_at or now
        playlist.updated_at = now
        playlists = [p for p in self.list() if p.id != playlist.id]
        playlists.append(playlist)
        self._save(playlists)
        return playlist

    def delete(self, playlist_id):
        self._save([p for p in self.list() if p.id != playlist_id])

    def _save(self, playlists):
        with _open_private(self._path) as f:
            json.dump([asdict(p) for p in playlists], f, indent=2)


class LocalLibraryService:
    def __init__(self, settings, bus, sync, store=None):
        self._settings = settings
        self._bus = bus
        self._sync = sync
        self._store = store or LocalPlaylistStore(dir=settings.data_dir)
        self._jobs = {}

    # ---- CRUD ----

    def list(self):
        return self._store.list()

    def get(self, playlist_id):
        playlist = self._store.get(playlist_id)
        if playlist is None:
            raise LocalPlaylistNotFoundError("That local playlist doesn't exist.")
        return playlist

    def create(self, name, description=""):
        return self._store.upsert(LocalPlaylist(name=name, description=description))

    def update_meta(self, playlist_id, *, name=None, description=None):
        playlist = self.get(playlist_id)
        if name is not None:
            playlist.name = name
        if description is not None:
            playlist.description = description
        return self._store.upsert(playlist)

    def delete(self, playlist_id):
        self._store.delete(playlist_id)

    def add_track(self, playlist_id, *, name, artist, album="", isrc="", duration_ms=None, image=""):
        playlist = self.get(playlist_id)
        playlist.tracks.append({
            "id": _new_id(), "name": name, "artist": artist, "album": album,
            "isrc": isrc, "duration_ms": duration_ms, "image": image,
            "added_at": _utc_now(), "links": {},
        })
        return self._store.upsert(playlist)

    def remove_tracks(self, playlist_id, track_ids):
        playlist = self.get(playlist_id)
        wanted = set(track_ids)
        playlist.tracks = [t for t in playlist.tracks if t["id"] not in wanted]
        return self._store.upsert(playlist)

    def bind(self, playlist_id, provider_id, provider_playlist_id):
        playlist = self.get(playlist_id)
        if provider_playlist_id:
            playlist.links[provider_id] = str(provider_playlist_id)
        else:
            playlist.links.pop(provider_id, None)
        return self._store.upsert(playlist)

    # ---- Clone / import ----

    def clone_from_provider(self, provider_id, provider_playlist_id):
        detail = PlaylistService(self._settings).detail(provider_id, provider_playlist_id)
        tracks = [
            _local_track_from_row(row, provider_id=provider_id, keep_occurrence=True)
            for row in detail["tracks"] if not row.get("unavailable")
        ]
        playlist = LocalPlaylist(
            name=detail["name"],
            description=detail.get("description") or "",
            image=detail.get("image") or "",
            tracks=tracks,
            links={provider_id: detail["id"]},
        )
        return self._store.upsert(playlist)

    @staticmethod
    def _parse_backup(content):
        """Accept either of SongMirror's own lossless backup encodings (see
        services/playlist_exports.py) — JSON or XML — and return the same
        normalized dict shape either way. `content` is the raw file text."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            try:
                data = parse_xml_backup(content)
            except ElementTree.ParseError as exc:
                raise LocalLibraryError(
                    "That file isn't a SongMirror playlist backup (unrecognized format)."
                ) from exc
        if not isinstance(data, dict) or data.get("kind") != BACKUP_KIND:
            raise LocalLibraryError("That file isn't a SongMirror playlist backup.")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise LocalLibraryError(
                f"Unsupported backup schema version {data.get('schema_version')!r} — "
                f"this SongMirror only reads version {SCHEMA_VERSION}."
            )
        return data

    def inspect_backup(self, content):
        """Stateless preview of a backup file's playlists for the import picker."""
        data = self._parse_backup(content)
        return {
            "provider": data.get("provider") or {},
            "playlists": [
                {"id": str(p.get("id") or ""), "name": p.get("name") or "",
                 "track_count": len(p.get("tracks") or [])}
                for p in data.get("playlists") or []
            ],
        }

    def import_backup(self, content, select_ids=None):
        """Import one or more playlists from a SongMirror backup (JSON or
        XML). Never auto-binds a live resync target — the backup's playlist id
        may belong to a different account/instance than whatever is connected
        here."""
        data = self._parse_backup(content)
        provider_id = (data.get("provider") or {}).get("id") or ""
        wanted = {str(i) for i in select_ids} if select_ids else None
        imported = []
        for entry in data.get("playlists") or []:
            if wanted is not None and str(entry.get("id") or "") not in wanted:
                continue
            tracks = [
                _local_track_from_row(row, provider_id=provider_id, keep_occurrence=False)
                for row in entry.get("tracks") or [] if not row.get("unavailable")
            ]
            playlist = LocalPlaylist(
                name=entry.get("name") or "Imported playlist",
                description=entry.get("description") or "",
                image=entry.get("image") or "",
                tracks=tracks,
            )
            imported.append(self._store.upsert(playlist))
        return imported

    # ---- Compare / pull ----

    def _target(self, provider_id):
        self._settings.apply_to_env()
        opts = parse_args([])
        sp = None
        cookie = (provider_id == "spotify" and spotify_write_backend() == "cookie"
                  and spotify_cookie.configured())
        if provider_id == "spotify" and not cookie:
            try:
                sp = spotify.client()
            except Exception as exc:
                raise LocalLibraryError(
                    "Spotify is not connected. Connect it on Accounts and retry."
                ) from exc
        target = build_one(provider_id, opts, sp)
        if target is None:
            raise LocalLibraryError(f"'{provider_id}' is not connected. Connect it on Accounts and retry.")
        return target

    def _bound_playlist(self, playlist, provider_id, target):
        dest_id = playlist.links.get(provider_id)
        if not dest_id:
            raise LocalLibraryError("Bind this playlist to a playlist on that service first.")
        dest_playlist = target.find_playlist(str(dest_id))
        if dest_playlist is None:
            raise LocalLibraryError("The bound playlist no longer exists on that service.")
        return dest_playlist

    def compare(self, playlist_id, provider_id):
        """Read-only diff: local (source of truth) vs. the bound live provider
        playlist. `to_push_add` is what a push would add; `provider_only` is
        what a push would remove (with removals enabled) — the same list is
        also what pull() can merge into the local playlist instead."""
        playlist = self.get(playlist_id)
        target = self._target(provider_id)
        dest_playlist = self._bound_playlist(playlist, provider_id, target)
        raw_provider_tracks = [_with_artist(t) for t in target.playlist_tracks(dest_playlist)]
        source_tracks = [_as_source_track(t) for t in playlist.tracks]
        expected = _expected_ids(playlist.tracks, provider_id)
        to_add, to_remove = compute_diff(source_tracks, raw_provider_tracks, expected, target.track_id)
        return {
            "to_push_add": [_diff_track_summary(t, track_id=t.get("id")) for t in to_add],
            "provider_only": [_diff_track_summary(t, track_id=target.track_id(t)) for t in to_remove],
        }

    def pull(self, playlist_id, provider_id, track_ids):
        """Merge explicitly selected provider-only tracks (from compare()'s
        provider_only list) into the local playlist."""
        playlist = self.get(playlist_id)
        target = self._target(provider_id)
        dest_playlist = self._bound_playlist(playlist, provider_id, target)
        wanted = {str(i) for i in track_ids}
        occurrence_of = getattr(target, "occurrence_id", lambda track: None)
        for raw in target.playlist_tracks(dest_playlist):
            raw = _with_artist(raw)
            tid = target.track_id(raw)
            if tid is None or str(tid) not in wanted:
                continue
            row = {
                "id": tid, "name": raw.get("name") or "", "artist": raw.get("artist") or "",
                "album": raw.get("album") or "", "isrc": raw.get("isrc") or "",
                "duration_ms": raw.get("duration_ms"), "image": raw.get("image") or "",
                "added_at": raw.get("added_at") or "", "occurrence_id": occurrence_of(raw),
            }
            playlist.tracks.append(_local_track_from_row(row, provider_id=provider_id, keep_occurrence=True))
        return self._store.upsert(playlist)

    # ---- Push (async job) ----

    def submit_push(self, playlist_id, provider_id, *, execute=False, allow_removals=False, max_removals=0):
        playlist = self.get(playlist_id)  # fail fast, before spawning the job
        job = {
            "id": _new_id(), "status": "queued",
            "playlist_id": playlist_id, "playlist_name": playlist.name, "provider": provider_id,
            "execute": bool(execute),
            "added": 0, "removed": 0, "missing": 0, "held": 0,
            "total": 0, "processed": 0,
            "not_found": [], "error": None,
        }
        self._jobs[job["id"]] = job
        asyncio.create_task(self._run_push(
            job, playlist_id, provider_id,
            execute=execute, allow_removals=allow_removals, max_removals=max_removals,
        ))
        return job

    def get_job(self, job_id):
        return self._jobs.get(job_id)

    async def _run_push(self, job, playlist_id, provider_id, *, execute, allow_removals, max_removals):
        job["status"] = "running"

        def on_progress(processed, total):
            job["processed"], job["total"] = processed, total

        def work():
            return self._push(playlist_id, provider_id, execute=execute, allow_removals=allow_removals,
                              max_removals=max_removals, on_progress=on_progress)

        try:
            result = await self._sync.run_exclusive(work)
            job["status"] = "done"
            job["added"], job["removed"] = result["added"], result["removed"]
            job["missing"], job["held"] = result["missing"], result["held"]
            job["not_found"] = result["not_found"]
        except LocalLibraryError as e:
            job["status"], job["error"] = "error", str(e)
        except Exception as e:
            job["status"], job["error"] = "error", repr(e)

    def _push(self, playlist_id, provider_id, *, execute, allow_removals, max_removals, on_progress=None):
        playlist = self.get(playlist_id)
        target = self._target(provider_id)
        dest_id = playlist.links.get(provider_id)
        if dest_id:
            dest_playlist = target.find_playlist(str(dest_id))
            if dest_playlist is None:
                raise LocalLibraryError("The bound playlist no longer exists on that service.")
        else:
            dest_playlist = target.create({"name": playlist.name, "description": playlist.description})
            playlist.links[provider_id] = str(target.playlist_id(dest_playlist))
            playlist = self._store.upsert(playlist)

        tag = "library"
        self._emit("section", f"push: {playlist.name} -> {target.name}", tag)

        raw_provider_tracks = [_with_artist(t) for t in target.playlist_tracks(dest_playlist)]
        source_tracks = [_as_source_track(t) for t in playlist.tracks]
        expected = _expected_ids(playlist.tracks, provider_id)
        to_add, to_remove = compute_diff(source_tracks, raw_provider_tracks, expected, target.track_id)

        cache = load_cache(target.cache_file)
        total = len(to_add)
        additions, not_found, new_links = [], [], {}
        for i, track in enumerate(to_add, 1):
            known = expected.get(track["id"])
            tid, method = (next(iter(known)), "link") if known else (None, None)
            if not tid:
                try:
                    tid, method = target.resolve(track, cache)
                except TargetAuthError:
                    raise
                except TargetTransientError as e:
                    self._emit("warn", f"push paused: provider is rate-limiting ({e}); "
                                       f"{total - i + 1} track(s) left for the next push", tag)
                    break
                except Exception as e:
                    self._emit("warn", f"resolve failed: {track['name']}: {e!r}", tag)
                    tid, method = None, None
            if not tid:
                not_found.append(track)
            else:
                additions.append((tid, method or "search", track))
                new_links[track["id"]] = str(tid)
            if on_progress:
                on_progress(i, total)
        save_cache(target.cache_file, cache)

        removals, held = protect_removals(to_remove, not_found)
        if not allow_removals or max_removals <= 0:
            held = held + removals
            removals = []
        elif len(removals) > max_removals:
            removals = removals[:max_removals]

        if execute:
            if additions:
                result = target.add(dest_playlist, [tid for tid, _method, _track in additions])
                additions, rejected = _split_add_results(additions, result, lambda item: item[0])
                for _tid, _method, track in rejected:
                    not_found.append(track)
                    new_links.pop(track["id"], None)
            for track in removals:
                target.remove(dest_playlist, track)

        for _tid, method, track in additions:
            self._emit("add", f"{track['name']} - {', '.join(track['artists'])}  ({method})", tag,
                       {"dry": not execute})
        for track in removals:
            self._emit("remove", f"{track['name']} - {track['artist']}", tag, {"dry": not execute})
        for track in held:
            self._emit("hold", f"kept on {target.name}: {track.get('name', '')} - {track.get('artist', '')}", tag)
        for track in not_found:
            self._emit("miss", f"no match on {target.name}: {track['name']} - {', '.join(track['artists'])}", tag)

        if execute and new_links:
            for local_id, tid in new_links.items():
                for t in playlist.tracks:
                    if t["id"] == local_id:
                        t.setdefault("links", {})[provider_id] = {"id": tid, "occurrence_id": ""}
            self._store.upsert(playlist)

        self._emit(
            "summary",
            f"{playlist.name}: +{len(additions)} -{len(removals)} "
            f"({len(not_found)} missing, {len(held)} held)",
            tag,
        )
        return {
            "added": len(additions), "removed": len(removals),
            "missing": len(not_found), "held": len(held),
            "not_found": [{"name": t["name"], "artist": ", ".join(t["artists"])} for t in not_found],
        }

    def _emit(self, kind, message, tag, data=None):
        self._bus.publish(logs.Event(time.time(), kind, tag, message, data))
