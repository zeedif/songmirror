"""Portable playlist backup formats and fresh provider snapshot behavior."""

import json
from datetime import datetime, timezone
from xml.etree import ElementTree


def _detail():
    return {
        "provider": "apple",
        "id": "playlist-1",
        "name": "Beyoncé & Friends",
        "description": "A <carefully> kept mix",
        "image": "https://img.test/playlist.jpg",
        "owned": True,
        "editable": True,
        "external_url": "https://music.apple.com/library/playlist/playlist-1",
        "tracks": [{
            "id": "track-1",
            "isrc": "USAAA2600001",
            "occurrence_id": "entry-1",
            "name": "Déjà Vu",
            "artist": "Beyoncé, Jay-Z",
            "album": None,
            "album_position": 7,
            "duration_ms": 183_999,
            "image": "https://img.test/track.jpg",
            "added_at": "2026-08-28T12:34:56Z",
            "external_url": "https://music.apple.com/song/track-1",
        }],
    }


def test_lossless_json_export_is_versioned_and_keeps_ordered_identity_metadata():
    from songmirror.services.playlist_exports import render_backup

    detail = _detail()
    detail["provider_headers"] = {"Authorization": "secret"}
    detail["tracks"][0]["raw"] = {"playbackToken": "secret"}
    result = render_backup(
        "apple",
        "Apple Music",
        [detail],
        "json",
        now=datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc),
    )
    body = json.loads(result.content)

    assert body["kind"] == "songmirror-playlist-backup"
    assert body["schema_version"] == 1
    assert body["exported_at"] == "2026-08-28T18:00:00Z"
    assert body["provider"] == {"id": "apple", "name": "Apple Music"}
    assert len(body["playlists"]) == 1
    assert len(body["playlists"][0]["tracks"]) == 1
    assert body["playlists"][0]["tracks"][0]["occurrence_id"] == "entry-1"
    assert body["playlists"][0]["tracks"][0]["isrc"] == "USAAA2600001"
    assert body["playlists"][0]["tracks"][0]["album_position"] == 7
    assert "provider_headers" not in body["playlists"][0]
    assert "raw" not in body["playlists"][0]["tracks"][0]
    assert result.media_type == "application/json"
    assert result.filename == (
        "songmirror-apple-music-beyonce-friends-20260828T180000Z.json"
    )


def test_xml_export_escapes_text_and_distinguishes_null_from_empty():
    from songmirror.services.playlist_exports import render_backup

    result = render_backup(
        "apple",
        "Apple Music",
        [_detail()],
        "xml",
        now=datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc),
    )
    root = ElementTree.fromstring(result.content)

    assert root.tag == "songmirror-playlist-backup"
    assert root.findtext("schema_version") == "1"
    assert root.findtext("playlists/playlist/description") == "A <carefully> kept mix"
    assert root.find("playlists/playlist/tracks/track/album").attrib == {"nil": "true"}
    assert root.findtext("playlists/playlist/tracks/track/album_position") == "7"
    assert root.findtext("playlists/playlist/tracks/track/name") == "Déjà Vu"
    assert result.media_type == "application/xml"


def test_soundiiz_export_follows_the_documented_import_array_shape():
    from songmirror.services.playlist_exports import render_backup

    result = render_backup(
        "apple",
        "Apple Music",
        [_detail()],
        "soundiiz",
        now=datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc),
    )
    rows = json.loads(result.content)

    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0] == {
        "platform": "applemusic",
        "type": "track",
        "id": "track-1",
        "title": "Déjà Vu",
        "artist": "Beyoncé, Jay-Z",
        "artistLink": "",
        "album": "",
        "albumLink": "",
        "isrc": "USAAA2600001",
        "duration": "183",
        "trackLink": "https://music.apple.com/song/track-1",
        "preview": "",
        "picture": "https://img.test/track.jpg",
        "addedDate": 1787920496,
        # Soundiiz calls the album's track number "position". It is not the
        # row's position in the playlist (which is zero in the backup above).
        "position": "7",
        "shareUrls": [],
    }
    assert result.filename.endswith(".soundiiz.json")


def test_soundiiz_does_not_substitute_playlist_order_for_missing_album_position():
    from songmirror.services.playlist_exports import render_backup

    detail = _detail()
    detail["tracks"][0].pop("album_position")
    detail["tracks"][0]["position"] = 42

    result = render_backup("apple", "Apple Music", [detail], "soundiiz")

    assert json.loads(result.content)[0]["position"] == ""


def test_provider_export_uses_one_target_and_snapshots_every_playlist_fresh(
    monkeypatch,
    tmp_path,
):
    from songmirror.services.playlists import PlaylistService
    from songmirror.services.settings import SettingsStore

    calls = []

    class Target:
        name = "Spotify"

        def browse_playlists(self):
            calls.append("browse")
            return [
                {"id": "2", "name": "Zulu"},
                {"id": "1", "name": "Alpha"},
            ]

        def playlist_tracks(self, playlist):
            calls.append(f"tracks:{playlist['id']}")
            return [{
                "id": f"track-{playlist['id']}",
                "name": playlist["name"],
                "artist": "Artist",
            }]

        def playlist_id(self, playlist):
            return playlist["id"]

        def playlist_name(self, playlist):
            return playlist["name"]

        def playlist_description(self, playlist):
            return ""

        def track_id(self, track):
            return track["id"]

        def is_editable(self, playlist):
            return True

    service = PlaylistService(SettingsStore(dir=tmp_path))
    target = Target()
    monkeypatch.setattr(service, "_target", lambda provider: target)

    result = service.export("spotify", "json")
    body = json.loads(result.content)

    assert calls == ["browse", "tracks:2", "tracks:1"]
    assert [playlist["name"] for playlist in body["playlists"]] == ["Alpha", "Zulu"]
    assert [playlist["tracks"][0]["name"] for playlist in body["playlists"]] == ["Alpha", "Zulu"]


def test_export_keeps_idless_catalog_ghosts_with_last_visible_metadata(
    monkeypatch,
    tmp_path,
):
    from songmirror.services.playlists import PlaylistService
    from songmirror.services.settings import SettingsStore

    class Target:
        name = "Apple Music"

        def find_playlist(self, playlist_id):
            return {"id": playlist_id, "name": "Rescued mix"}

        def playlist_tracks(self, playlist):
            return [{
                "catalog_id": None,
                "relationship_id": "library-entry-9",
                "name": "Delisted favorite",
                "artist": "Remembered Artist",
                "album": "Original Album",
                "album_position": 4,
            }]

        def playlist_id(self, playlist):
            return playlist["id"]

        def playlist_name(self, playlist):
            return playlist["name"]

        def playlist_description(self, playlist):
            return ""

        def track_id(self, track):
            return track["catalog_id"]

        def occurrence_id(self, track):
            return track["relationship_id"]

        def is_editable(self, playlist):
            return True

    service = PlaylistService(SettingsStore(dir=tmp_path))
    monkeypatch.setattr(service, "_target", lambda provider: Target())

    result = service.export("apple", "json", playlist_id="playlist-1")
    body = json.loads(result.content)
    track = body["playlists"][0]["tracks"][0]

    assert len(body["playlists"][0]["tracks"]) == 1
    assert track == {
        "id": "",
        "isrc": "",
        "occurrence_id": "library-entry-9",
        "name": "Delisted favorite",
        "artist": "Remembered Artist",
        "album": "Original Album",
        "album_position": 4,
        "duration_ms": None,
        "image": "",
        "added_at": "",
        "external_url": "",
        "unavailable": True,
    }
