"""LocalPlaylistStore CRUD, clone/import mapping, and the compare/pull/push
diff flow against a fake MirrorTarget (mirrors tests/test_transfers.py's
approach of faking the provider boundary rather than hitting a real API)."""

import asyncio

import pytest

from songmirror.services.events import EventBus
from songmirror.services.local_playlists import (
    LocalLibraryError, LocalLibraryService, LocalPlaylist, LocalPlaylistNotFoundError,
    LocalPlaylistStore,
)
from songmirror.services.playlist_exports import BACKUP_KIND, SCHEMA_VERSION
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
    assert playlist.origin == {"provider": "spotify", "playlist_id": "pl1", "imported": False}
    assert len(playlist.tracks) == 1  # the unavailable ghost track was skipped
    track = playlist.tracks[0]
    assert track["name"] == "Song" and track["isrc"] == "ISRC1"
    assert track["links"] == {"spotify": {"id": "t1", "occurrence_id": "occ1"}}


def _backup(playlists):
    return {
        "kind": BACKUP_KIND, "schema_version": SCHEMA_VERSION,
        "exported_at": "2026-01-01T00:00:00Z",
        "provider": {"id": "spotify", "name": "Spotify"},
        "playlist_count": len(playlists),
        "track_count": sum(len(p["tracks"]) for p in playlists),
        "playlists": playlists,
    }


def test_inspect_backup_rejects_wrong_kind_and_version(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(LocalLibraryError):
        svc.inspect_backup({"kind": "something-else"})
    with pytest.raises(LocalLibraryError):
        svc.inspect_backup({"kind": BACKUP_KIND, "schema_version": SCHEMA_VERSION + 1})


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
    [playlist] = svc.import_backup(backup)

    assert playlist.name == "Español"
    assert playlist.links == {}  # never auto-bound to a live playlist
    assert playlist.origin == {"provider": "spotify", "playlist_id": "pl1", "imported": True}
    track = playlist.tracks[0]
    assert track["links"] == {"spotify": {"id": "t1", "occurrence_id": ""}}  # catalog id kept, occurrence dropped


def test_import_backup_select_ids_filters_playlists(tmp_path):
    backup = _backup([
        {"provider": "spotify", "id": "pl1", "name": "Keep", "description": "", "tracks": []},
        {"provider": "spotify", "id": "pl2", "name": "Skip", "description": "", "tracks": []},
    ])
    svc = _service(tmp_path)
    imported = svc.import_backup(backup, select_ids=["pl1"])
    assert [p.name for p in imported] == ["Keep"]


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
    assert playlist.tracks[0]["links"] == {"apple": {"id": "p1", "occurrence_id": ""}}


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
