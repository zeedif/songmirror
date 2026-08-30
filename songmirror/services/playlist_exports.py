"""Portable, versioned playlist-metadata backups.

The export intentionally contains normalized catalog metadata only. Provider
credentials, request headers, cookies, and raw API payloads never cross this
boundary, which makes the resulting JSON/XML files safe to keep separately
from SongMirror's private data directory.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.etree import ElementTree

from anyascii import anyascii


BACKUP_KIND = "songmirror-playlist-backup"
SCHEMA_VERSION = 1
SUPPORTED_FORMATS = frozenset({"json", "xml", "soundiiz"})

_PLAYLIST_FIELDS = (
    "provider",
    "id",
    "name",
    "description",
    "count",
    "image",
    "owned",
    "editable",
    "external_url",
)
_TRACK_FIELDS = (
    "position",
    "id",
    "isrc",
    "occurrence_id",
    "name",
    "artist",
    "album",
    "album_position",
    "duration_ms",
    "image",
    "added_at",
    "external_url",
    "unavailable",
)


@dataclass(frozen=True)
class PlaylistExport:
    content: bytes
    media_type: str
    filename: str


def _utc_timestamp(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def build_backup(provider_id, provider_name, playlists, *, now=None):
    """Return the stable, provider-neutral backup document before encoding.

    Project through explicit allowlists even though PlaylistService already
    normalizes these dictionaries. That keeps future provider-only/raw fields
    (and, critically, auth material) from accidentally entering the format.
    """
    normalized_playlists = []
    for playlist in playlists:
        normalized = {field: playlist.get(field) for field in _PLAYLIST_FIELDS}
        normalized["tracks"] = []
        for track in playlist.get("tracks") or []:
            normalized_track = {field: track.get(field) for field in _TRACK_FIELDS}
            normalized_track["unavailable"] = bool(track.get("unavailable", False))
            normalized["tracks"].append(normalized_track)
        normalized_playlists.append(normalized)
    return {
        "kind": BACKUP_KIND,
        "schema_version": SCHEMA_VERSION,
        "exported_at": _utc_timestamp(now),
        "provider": {"id": str(provider_id), "name": str(provider_name)},
        "playlist_count": len(normalized_playlists),
        "track_count": sum(
            len(playlist["tracks"]) for playlist in normalized_playlists
        ),
        "playlists": normalized_playlists,
    }


def _append_xml_value(parent, tag, value):
    element = ElementTree.SubElement(parent, tag)
    if value is None:
        element.set("nil", "true")
    elif isinstance(value, bool):
        element.text = "true" if value else "false"
    else:
        element.text = str(value)
    return element


def _as_xml(backup):
    root = ElementTree.Element(BACKUP_KIND)
    _append_xml_value(root, "schema_version", backup["schema_version"])
    _append_xml_value(root, "exported_at", backup["exported_at"])

    provider = ElementTree.SubElement(root, "provider")
    _append_xml_value(provider, "id", backup["provider"]["id"])
    _append_xml_value(provider, "name", backup["provider"]["name"])
    _append_xml_value(root, "playlist_count", backup["playlist_count"])
    _append_xml_value(root, "track_count", backup["track_count"])

    playlists = ElementTree.SubElement(root, "playlists")
    for playlist_data in backup["playlists"]:
        playlist = ElementTree.SubElement(playlists, "playlist")
        for field in _PLAYLIST_FIELDS:
            _append_xml_value(playlist, field, playlist_data.get(field))
        tracks = ElementTree.SubElement(playlist, "tracks")
        for track_data in playlist_data.get("tracks") or []:
            track = ElementTree.SubElement(tracks, "track")
            for field in _TRACK_FIELDS:
                _append_xml_value(track, field, track_data.get(field))

    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


_PLAYLIST_INT_FIELDS = frozenset({"count"})
_PLAYLIST_BOOL_FIELDS = frozenset({"owned", "editable"})
_TRACK_INT_FIELDS = frozenset({"position", "album_position", "duration_ms"})
_TRACK_BOOL_FIELDS = frozenset({"unavailable"})


def _xml_text(element):
    if element is None or element.get("nil") == "true":
        return None
    return element.text


def _xml_int(element):
    text = _xml_text(element)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _xml_bool(element):
    return _xml_text(element) == "true"


def _xml_row(element, fields, int_fields, bool_fields):
    row = {}
    for field in fields:
        child = element.find(field)
        if field in int_fields:
            row[field] = _xml_int(child)
        elif field in bool_fields:
            row[field] = _xml_bool(child)
        else:
            row[field] = _xml_text(child)
    return row


def parse_xml_backup(content):
    """Reverse of _as_xml(): parse a SongMirror XML backup back into the same
    dict shape build_backup() produces, so it can be validated/consumed
    exactly like a JSON one. Raises xml.etree.ElementTree.ParseError on
    malformed XML — callers decide how to report that."""
    root = ElementTree.fromstring(content)
    provider_el = root.find("provider")
    playlists = []
    for playlist_el in root.findall("playlists/playlist"):
        playlist = _xml_row(playlist_el, _PLAYLIST_FIELDS, _PLAYLIST_INT_FIELDS, _PLAYLIST_BOOL_FIELDS)
        playlist["tracks"] = [
            _xml_row(track_el, _TRACK_FIELDS, _TRACK_INT_FIELDS, _TRACK_BOOL_FIELDS)
            for track_el in playlist_el.findall("tracks/track")
        ]
        playlists.append(playlist)
    return {
        "kind": root.tag,
        "schema_version": _xml_int(root.find("schema_version")),
        "exported_at": _xml_text(root.find("exported_at")),
        "provider": {
            "id": _xml_text(provider_el.find("id")) if provider_el is not None else "",
            "name": _xml_text(provider_el.find("name")) if provider_el is not None else "",
        },
        "playlist_count": _xml_int(root.find("playlist_count")),
        "track_count": _xml_int(root.find("track_count")),
        "playlists": playlists,
    }


def _filename_part(value, fallback):
    value = re.sub(r"[^a-z0-9]+", "-", anyascii(str(value)).casefold()).strip("-")
    return (value[:80].rstrip("-") or fallback)


def _soundiiz_platform(provider_id):
    return {
        "amazon": "amazonmusic",
        "apple": "applemusic",
        "ytmusic": "youtubemusic",
    }.get(str(provider_id), str(provider_id))


def _epoch_seconds(value):
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}", text):
        try:
            return int(datetime(int(text), 1, 1, tzinfo=timezone.utc).timestamp())
        except ValueError:
            return None
    try:
        seconds = float(text)
        while abs(seconds) > 32_503_680_000:
            seconds /= 1_000
        return int(seconds)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (ValueError, OverflowError):
        return None


def _as_soundiiz(provider_id, playlist):
    """Map one playlist to Soundiiz's documented, importable JSON array."""
    rows = []
    for track in playlist.get("tracks") or []:
        duration_ms = track.get("duration_ms")
        try:
            duration = str(max(0, int(float(duration_ms)) // 1_000))
        except (TypeError, ValueError):
            duration = ""
        try:
            album_position = int(track.get("album_position"))
            position = str(album_position) if album_position > 0 else ""
        except (TypeError, ValueError):
            position = ""
        rows.append({
            "platform": _soundiiz_platform(provider_id),
            "type": "track",
            "id": str(track.get("id") or ""),
            "title": str(track.get("name") or ""),
            "artist": str(track.get("artist") or ""),
            "artistLink": "",
            "album": str(track.get("album") or ""),
            "albumLink": "",
            "isrc": str(track.get("isrc") or ""),
            "duration": duration,
            "trackLink": str(track.get("external_url") or ""),
            "preview": "",
            "picture": str(track.get("image") or ""),
            "addedDate": _epoch_seconds(track.get("added_at")),
            "position": position,
            "shareUrls": [],
        })
    return rows


def render_backup(
    provider_id,
    provider_name,
    playlists,
    export_format,
    *,
    now=None,
    filename_scope=None,
):
    """Encode a backup and provide safe browser-download response metadata."""
    export_format = str(export_format).casefold()
    if export_format not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported playlist export format: {export_format}")

    backup = build_backup(provider_id, provider_name, playlists, now=now)
    if export_format == "soundiiz":
        if len(backup["playlists"]) != 1:
            raise ValueError("Soundiiz JSON exports contain exactly one playlist")
        content = (
            json.dumps(
                _as_soundiiz(provider_id, backup["playlists"][0]),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        media_type = "application/json"
    elif export_format == "json":
        content = (json.dumps(backup, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        media_type = "application/json"
    else:
        content = _as_xml(backup)
        media_type = "application/xml"

    provider_part = _filename_part(provider_name or provider_id, "provider")
    if filename_scope:
        scope_part = _filename_part(filename_scope, "playlists")
    elif len(backup["playlists"]) == 1:
        scope_part = _filename_part(backup["playlists"][0].get("name"), "playlist")
    else:
        scope_part = "all-playlists"
    timestamp = re.sub(r"[-:]", "", backup["exported_at"])
    suffix = "soundiiz.json" if export_format == "soundiiz" else export_format
    filename = f"songmirror-{provider_part}-{scope_part}-{timestamp}.{suffix}"
    return PlaylistExport(content=content, media_type=media_type, filename=filename)
