"""LocalPlaylistStore CRUD, clone/import mapping, and the compare/pull/push
diff flow against a fake MirrorTarget (mirrors tests/test_transfers.py's
approach of faking the provider boundary rather than hitting a real API)."""

import asyncio
import json

import pytest

from songmirror.services.events import EventBus
from songmirror.services.local_playlists import (
    LocalLibraryError, LocalLibraryService, LocalPlaylist, LocalPlaylistNotFoundError,
    LocalPlaylistStore,
)
from songmirror.services.playlist_exports import BACKUP_KIND, SCHEMA_VERSION, render_backup
from songmirror.services.playlists import PlaylistService
from songmirror.services.settings import SettingsStore
from songmirror.services.sync_service import SyncService


def test_store_upsert_assigns_id_and_round_trips(tmp_path):
    store = LocalPlaylistStore(dir=tmp_path)
    saved = store.upsert(LocalPlaylist(name="Español"))
    assert saved.id and saved.created_at and saved.updated_at

    reloaded = store.get(saved.id)
    assert reloaded.name == "Español"

    saved.name = "Español (renamed)"
    store.upsert(saved)
    assert store.get(saved.id).name == "Español (renamed)"
    assert len(store.list()) == 1  # re-saved, not duplicated


def test_store_delete_removes_only_that_playlist(tmp_path):
    store = LocalPlaylistStore(dir=tmp_path)
    a = store.upsert(LocalPlaylist(name="A"))
    b = store.upsert(LocalPlaylist(name="B"))
    store.delete(a.id)
    assert [p.id for p in store.list()] == [b.id]


def _service(tmp_path, bus=None, sync=None):
    settings = SettingsStore(dir=tmp_path)
    bus = bus or EventBus()
    sync = sync or SyncService(settings, bus)
    return LocalLibraryService(settings, bus, sync, store=LocalPlaylistStore(dir=tmp_path))


def test_get_missing_playlist_raises_not_found(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(LocalPlaylistNotFoundError):
        svc.get("nope")


def test_add_and_remove_tracks(tmp_path):
    svc = _service(tmp_path)
    playlist = svc.create("Mixtape")
    playlist = svc.add_track(playlist.id, name="Song", artist="Artist")
    assert len(playlist.tracks) == 1
    track_id = playlist.tracks[0]["id"]

    playlist = svc.remove_tracks(playlist.id, [track_id])
    assert playlist.tracks == []


def test_clone_from_provider_maps_tracks_and_binds_link(tmp_path, monkeypatch):
    def fake_detail(self, provider_id, playlist_id, **kwargs):
        return {
            "provider": provider_id, "id": playlist_id, "name": "Español",
            "description": "", "image": "",
            "tracks": [
                {"position": 0, "id": "t1", "isrc": "ISRC1", "occurrence_id": "occ1",
                 "name": "Song", "artist": "Artist", "album": "Album", "duration_ms": 1000,
                 "image": "", "added_at": "2020", "external_url": ""},
                {"position": 1, "id": "t2", "isrc": "", "occurrence_id": "",
                 "name": "Ghost", "artist": "Artist", "album": "", "duration_ms": None,
                 "image": "", "added_at": "", "external_url": "", "unavailable": True},
            ],
        }

    monkeypatch.setattr(PlaylistService, "detail", fake_detail)
    svc = _service(tmp_path)
    playlist = svc.clone_from_provider("spotify", "pl1")

    assert playlist.name == "Español"
    assert playlist.links == {"spotify": "pl1"}
    assert len(playlist.tracks) == 1  # the unavailable ghost track was skipped
    track = playlist.tracks[0]
    assert track["name"] == "Song" and track["isrc"] == "ISRC1"
    assert track["links"] == {
        "spotify": {"id": "t1", "occurrence_id": "occ1", "external_url": "", "image": ""}
    }


def _backup(playlists):
    return {
        "kind": BACKUP_KIND, "schema_version": SCHEMA_VERSION,
        "exported_at": "2026-01-01T00:00:00Z",
        "provider": {"id": "spotify", "name": "Spotify"},
        "playlists": playlists,
    }


def test_inspect_backup_rejects_wrong_kind_and_version(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(LocalLibraryError):
        svc.inspect_backup(json.dumps({"kind": "something-else"}))
    with pytest.raises(LocalLibraryError):
        svc.inspect_backup(json.dumps({"kind": BACKUP_KIND, "schema_version": SCHEMA_VERSION + 1}))


def test_inspect_backup_rejects_unrecognized_file_content(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(LocalLibraryError):
        svc.inspect_backup("this is neither JSON nor XML")


def test_import_backup_maps_tracks_without_binding_a_live_target(tmp_path):
    backup = _backup([{
        "provider": "spotify", "id": "pl1", "name": "Español", "description": "",
        "tracks": [
            {"position": 0, "id": "t1", "isrc": "ISRC1", "occurrence_id": "occ-from-old-account",
             "name": "Song", "artist": "Artist", "album": "", "album_position": 1,
             "duration_ms": 1000, "image": "", "added_at": "2020", "external_url": "",
             "unavailable": False},
        ],
    }])
    svc = _service(tmp_path)
    [playlist] = svc.import_backup(json.dumps(backup))

    assert playlist.name == "Español"
    assert playlist.links == {}  # never auto-bound to a live playlist
    track = playlist.tracks[0]
    # catalog id kept, occurrence dropped
    assert track["links"] == {
        "spotify": {"id": "t1", "occurrence_id": "", "external_url": "", "image": ""}
    }


def test_import_backup_select_ids_filters_playlists(tmp_path):
    backup = _backup([
        {"provider": "spotify", "id": "pl1", "name": "Keep", "description": "", "tracks": []},
        {"provider": "spotify", "id": "pl2", "name": "Skip", "description": "", "tracks": []},
    ])
    svc = _service(tmp_path)
    imported = svc.import_backup(json.dumps(backup), select_ids=["pl1"])
    assert [p.name for p in imported] == ["Keep"]


def test_export_backup_uses_the_local_kind_and_keeps_the_full_links_map(tmp_path, monkeypatch):
    from songmirror.services.local_playlists import LOCAL_BACKUP_KIND, LOCAL_SCHEMA_VERSION

    def fake_detail(self, provider_id, playlist_id, **kwargs):
        return {
            "provider": provider_id, "id": playlist_id, "name": "Multi", "description": "", "image": "",
            "tracks": [{"id": "sp1", "isrc": "ISRC1", "name": "Song", "artist": "Artist",
                        "external_url": "https://open.spotify.com/track/sp1", "image": "img"}],
        }

    monkeypatch.setattr(PlaylistService, "detail", fake_detail)
    svc = _service(tmp_path)
    playlist = svc.clone_from_provider("spotify", "pl1")
    # A track matched on a second service too, as pull()/push() would leave it.
    playlist.tracks[0]["links"]["tidal"] = {
        "id": "td1", "occurrence_id": "", "external_url": "https://listen.tidal.com/track/td1", "image": "",
    }
    svc._store.upsert(playlist)

    exported = svc.export_backup([playlist.id])

    assert exported["kind"] == LOCAL_BACKUP_KIND
    assert exported["schema_version"] == LOCAL_SCHEMA_VERSION
    [entry] = exported["playlists"]
    assert entry["name"] == "Multi"
    [track] = entry["tracks"]
    assert track["links"] == {
        "spotify": {"id": "sp1", "occurrence_id": "", "external_url": "https://open.spotify.com/track/sp1", "image": "img"},
        "tidal": {"id": "td1", "occurrence_id": "", "external_url": "https://listen.tidal.com/track/td1", "image": ""},
    }


def test_export_backup_only_includes_the_selected_ids(tmp_path):
    svc = _service(tmp_path)
    keep = svc.create("Keep")
    svc.create("Skip")
    exported = svc.export_backup([keep.id])
    assert [p["name"] for p in exported["playlists"]] == ["Keep"]


def test_import_backup_round_trips_a_local_kind_export(tmp_path):
    svc = _service(tmp_path)
    original = svc.create("Español")
    original = svc.add_track(original.id, name="Song", artist="Artist", isrc="ISRC1")
    original.tracks[0]["links"] = {
        "spotify": {"id": "sp1", "occurrence_id": "", "external_url": "https://open.spotify.com/track/sp1", "image": ""},
    }
    svc._store.upsert(original)

    exported = svc.export_backup([original.id])
    [imported] = svc.import_backup(json.dumps(exported))

    assert imported.id != original.id  # a fresh local identity, not the same record
    assert imported.name == "Español"
    assert len(imported.tracks) == 1
    assert imported.tracks[0]["id"] != original.tracks[0]["id"]
    assert imported.tracks[0]["isrc"] == "ISRC1"
    assert imported.tracks[0]["links"] == original.tracks[0]["links"]


def test_inspect_backup_rejects_wrong_local_schema_version(tmp_path):
    from songmirror.services.local_playlists import LOCAL_BACKUP_KIND

    svc = _service(tmp_path)
    with pytest.raises(LocalLibraryError):
        svc.inspect_backup(json.dumps({"kind": LOCAL_BACKUP_KIND, "schema_version": 999, "playlists": []}))


def _xml_backup_text(playlists):
    """A genuine XML export, rendered through the app's own export path —
    the most faithful stand-in for a file a user actually downloaded."""
    result = render_backup("spotify", "Spotify", playlists, "xml")
    return result.content.decode("utf-8")


def test_inspect_and_import_accept_the_app_s_own_xml_export(tmp_path):
    playlists = [{
        "provider": "spotify", "id": "pl1", "name": "Español", "description": "",
        "count": 2, "image": "", "owned": True, "editable": True, "external_url": "",
        "tracks": [
            {"position": 0, "id": "t1", "isrc": "ISRC1", "occurrence_id": "occ1",
             "name": "Song", "artist": "Artist", "album": "Album", "album_position": 1,
             "duration_ms": 1000, "image": "", "added_at": "2020", "external_url": "",
             "unavailable": False},
            {"position": 1, "id": "t2", "isrc": "", "occurrence_id": "",
             "name": "Ghost", "artist": "Artist", "album": "", "album_position": None,
             "duration_ms": None, "image": "", "added_at": "", "external_url": "",
             "unavailable": True},
        ],
    }]
    xml_text = _xml_backup_text(playlists)
    svc = _service(tmp_path)

    preview = svc.inspect_backup(xml_text)
    assert preview["playlists"] == [{"id": "pl1", "name": "Español", "track_count": 2}]

    [playlist] = svc.import_backup(xml_text)
    assert playlist.name == "Español"
    assert len(playlist.tracks) == 1  # the unavailable ghost track was skipped, same as the JSON path
    track = playlist.tracks[0]
    assert track["name"] == "Song" and track["isrc"] == "ISRC1"
    assert track["duration_ms"] == 1000  # correctly coerced back from XML text to a real int, not "1000"


class _FakeTarget:
    def __init__(self, tracks, cache_file, name="Prov", source="apple"):
        self.name, self.source, self.cache_file = name, source, str(cache_file)
        self._tracks = tracks
        self.added, self.removed, self.created = [], [], None

    def playlist_tracks(self, pl):
        return self._tracks

    def track_id(self, t):
        return t.get("id")

    def find_playlist(self, playlist_id):
        return {"id": playlist_id, "name": "Dest"} if playlist_id else None

    def playlist_id(self, pl):
        return pl.get("id")

    def create(self, spec):
        self.created = spec
        return {"id": "new-pl", "name": spec["name"]}

    def resolve(self, track, cache):
        return (f"dest-{track['name']}", "search")

    def add(self, pl, ids):
        self.added.extend(ids)
        return None

    def remove(self, pl, track):
        self.removed.append(track)


def test_compare_reports_push_adds_and_provider_only_tracks(tmp_path):
    svc = _service(tmp_path)
    playlist = svc.create("Mixtape")
    playlist = svc.add_track(playlist.id, name="Local Only", artist="A")
    target = _FakeTarget(
        [{"id": "p1", "name": "Provider Only", "artist": "B", "duration_ms": 1000}],
        tmp_path / "cache.json",
    )
    svc.bind(playlist.id, "apple", "dest1")
    svc._target = lambda provider_id: target

    result = svc.compare(playlist.id, "apple")
    assert [t["name"] for t in result["to_push_add"]] == ["Local Only"]
    assert [t["name"] for t in result["provider_only"]] == ["Provider Only"]


def test_compare_handles_provider_tracks_with_no_singular_artist_key(tmp_path):
    """Spotify's raw playlist-track dict (every read path) carries only an
    "artists" list, no "artist" string, unlike every other provider — this
    used to crash compute_diff() with a KeyError."""
    svc = _service(tmp_path)
    playlist = svc.create("Mixtape")
    playlist = svc.add_track(playlist.id, name="Local Only", artist="A")
    target = _FakeTarget(
        [{"id": "p1", "name": "Provider Only", "artists": ["B"], "duration_ms": 1000}],
        tmp_path / "cache.json",
    )
    svc.bind(playlist.id, "apple", "dest1")
    svc._target = lambda provider_id: target

    result = svc.compare(playlist.id, "apple")
    assert [t["name"] for t in result["to_push_add"]] == ["Local Only"]
    assert [t["name"] for t in result["provider_only"]] == ["Provider Only"]
    assert result["provider_only"][0]["artist"] == "B"


def test_compare_requires_a_bound_playlist(tmp_path):
    svc = _service(tmp_path)
    playlist = svc.create("Mixtape")
    with pytest.raises(LocalLibraryError):
        svc.compare(playlist.id, "apple")


def test_pull_merges_selected_provider_tracks(tmp_path):
    svc = _service(tmp_path)
    playlist = svc.create("Mixtape")
    target = _FakeTarget(
        [{"id": "p1", "name": "Provider Track", "artist": "B", "duration_ms": 1000}],
        tmp_path / "cache.json",
    )
    svc.bind(playlist.id, "apple", "dest1")
    svc._target = lambda provider_id: target

    playlist = svc.pull(playlist.id, "apple", ["p1"])
    assert len(playlist.tracks) == 1
    assert playlist.tracks[0]["name"] == "Provider Track"
    assert playlist.tracks[0]["links"] == {
        "apple": {"id": "p1", "occurrence_id": "", "external_url": "https://music.apple.com/song/p1", "image": ""}
    }


def test_pull_derives_artist_from_artists_list_when_singular_key_missing(tmp_path):
    svc = _service(tmp_path)
    playlist = svc.create("Mixtape")
    target = _FakeTarget(
        [{"id": "p1", "name": "Provider Track", "artists": ["B"], "duration_ms": 1000}],
        tmp_path / "cache.json",
    )
    svc.bind(playlist.id, "apple", "dest1")
    svc._target = lambda provider_id: target

    playlist = svc.pull(playlist.id, "apple", ["p1"])
    assert playlist.tracks[0]["artist"] == "B"


async def _await_job(svc, job_id):
    for _ in range(200):
        job = svc.get_job(job_id)
        if job and job["status"] in ("done", "error"):
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("push job never finished")


def test_push_dry_run_adds_nothing_but_reports_the_diff(tmp_path):
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        settings = SettingsStore(dir=tmp_path)
        sync = SyncService(settings, bus)
        svc = LocalLibraryService(settings, bus, sync, store=LocalPlaylistStore(dir=tmp_path))
        playlist = svc.create("Mixtape")
        playlist = svc.add_track(playlist.id, name="New Song", artist="A")
        target = _FakeTarget([], tmp_path / "cache.json")
        svc.bind(playlist.id, "apple", "dest1")
        svc._target = lambda provider_id: target

        job = svc.submit_push(playlist.id, "apple", execute=False)
        finished = await _await_job(svc, job["id"])
        assert finished["status"] == "done"
        assert finished["added"] == 1
        assert target.added == []  # dry run — nothing actually written

    asyncio.run(scenario())


def test_push_execute_writes_adds_and_remembers_the_link(tmp_path):
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        settings = SettingsStore(dir=tmp_path)
        sync = SyncService(settings, bus)
        store = LocalPlaylistStore(dir=tmp_path)
        svc = LocalLibraryService(settings, bus, sync, store=store)
        playlist = svc.create("Mixtape")
        playlist = svc.add_track(playlist.id, name="New Song", artist="A")
        target = _FakeTarget([], tmp_path / "cache.json")
        svc.bind(playlist.id, "apple", "dest1")
        svc._target = lambda provider_id: target

        job = svc.submit_push(playlist.id, "apple", execute=True)
        finished = await _await_job(svc, job["id"])
        assert finished["status"] == "done" and finished["added"] == 1
        assert target.added == ["dest-New Song"]

        reloaded = store.get(playlist.id)
        assert reloaded.tracks[0]["links"]["apple"]["id"] == "dest-New Song"

    asyncio.run(scenario())


def test_push_removals_are_held_back_unless_explicitly_allowed(tmp_path):
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        settings = SettingsStore(dir=tmp_path)
        sync = SyncService(settings, bus)
        svc = LocalLibraryService(settings, bus, sync, store=LocalPlaylistStore(dir=tmp_path))
        playlist = svc.create("Mixtape")  # no local tracks
        target = _FakeTarget(
            [{"id": "p1", "name": "Only On Provider", "artist": "B", "duration_ms": 1000}],
            tmp_path / "cache.json",
        )
        svc.bind(playlist.id, "apple", "dest1")
        svc._target = lambda provider_id: target

        job = svc.submit_push(playlist.id, "apple", execute=True, allow_removals=False)
        finished = await _await_job(svc, job["id"])
        assert finished["removed"] == 0
        assert finished["held"] == 1
        assert target.removed == []

    asyncio.run(scenario())


def test_push_removals_apply_when_allowed_and_under_cap(tmp_path):
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        settings = SettingsStore(dir=tmp_path)
        sync = SyncService(settings, bus)
        svc = LocalLibraryService(settings, bus, sync, store=LocalPlaylistStore(dir=tmp_path))
        playlist = svc.create("Mixtape")
        target = _FakeTarget(
            [{"id": "p1", "name": "Only On Provider", "artist": "B", "duration_ms": 1000}],
            tmp_path / "cache.json",
        )
        svc.bind(playlist.id, "apple", "dest1")
        svc._target = lambda provider_id: target

        job = svc.submit_push(playlist.id, "apple", execute=True, allow_removals=True, max_removals=5)
        finished = await _await_job(svc, job["id"])
        assert finished["removed"] == 1
        assert len(target.removed) == 1

    asyncio.run(scenario())


def test_push_removal_handles_provider_tracks_with_no_singular_artist_key(tmp_path):
    """Same Spotify-shaped-track regression as compare(), but on the push path
    — the removal emit line also indexed "artist" directly."""
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        settings = SettingsStore(dir=tmp_path)
        sync = SyncService(settings, bus)
        svc = LocalLibraryService(settings, bus, sync, store=LocalPlaylistStore(dir=tmp_path))
        playlist = svc.create("Mixtape")
        target = _FakeTarget(
            [{"id": "p1", "name": "Only On Provider", "artists": ["B"], "duration_ms": 1000}],
            tmp_path / "cache.json",
        )
        svc.bind(playlist.id, "apple", "dest1")
        svc._target = lambda provider_id: target

        job = svc.submit_push(playlist.id, "apple", execute=True, allow_removals=True, max_removals=5)
        finished = await _await_job(svc, job["id"])
        assert finished["status"] == "done"
        assert finished["removed"] == 1
        assert len(target.removed) == 1

    asyncio.run(scenario())


def test_push_creates_a_destination_playlist_when_unbound(tmp_path):
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        settings = SettingsStore(dir=tmp_path)
        sync = SyncService(settings, bus)
        store = LocalPlaylistStore(dir=tmp_path)
        svc = LocalLibraryService(settings, bus, sync, store=store)
        playlist = svc.create("Mixtape", description="desc")
        target = _FakeTarget([], tmp_path / "cache.json")
        svc._target = lambda provider_id: target  # not bound to "apple" yet

        job = svc.submit_push(playlist.id, "apple", execute=True)
        await _await_job(svc, job["id"])

        assert target.created == {"name": "Mixtape", "description": "desc"}
        assert store.get(playlist.id).links["apple"] == "new-pl"

    asyncio.run(scenario())
