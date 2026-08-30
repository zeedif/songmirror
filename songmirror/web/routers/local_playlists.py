"""Local playlist library — CRUD, clone/import, compare/pull, and push."""

from dataclasses import asdict

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from ...services.local_playlists import LocalLibraryError

router = APIRouter()


def _service(request: Request):
    return request.app.state.local_playlists


def _handled(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LocalLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/api/local-playlists")
def list_local_playlists(request: Request):
    return [asdict(p) for p in _service(request).list()]


@router.post("/api/local-playlists")
def create_local_playlist(request: Request, body: dict = Body(...)):
    playlist = _handled(_service(request).create, body["name"], body.get("description", ""))
    return asdict(playlist)


@router.post("/api/local-playlists/clone")
def clone_local_playlist(request: Request, body: dict = Body(...)):
    playlist = _handled(_service(request).clone_from_provider, body["provider"], body["playlist_id"])
    return asdict(playlist)


@router.post("/api/local-playlists/import/inspect")
def inspect_local_playlist_backup(request: Request, body: dict = Body(...)):
    return _handled(_service(request).inspect_backup, body["content"])


@router.post("/api/local-playlists/import")
def import_local_playlist_backup(request: Request, body: dict = Body(...)):
    imported = _handled(_service(request).import_backup, body["content"], body.get("select_ids"))
    return [asdict(p) for p in imported]


@router.get("/api/local-playlists/push-jobs/{job_id}")
def local_playlist_push_job(job_id: str, request: Request):
    job = _service(request).get_job(job_id)
    if not job:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return job


@router.get("/api/local-playlists/{playlist_id}")
def get_local_playlist(playlist_id: str, request: Request):
    return asdict(_handled(_service(request).get, playlist_id))


@router.put("/api/local-playlists/{playlist_id}")
def update_local_playlist(playlist_id: str, request: Request, body: dict = Body(...)):
    playlist = _handled(
        _service(request).update_meta,
        playlist_id,
        name=body.get("name"),
        description=body.get("description"),
    )
    return asdict(playlist)


@router.delete("/api/local-playlists/{playlist_id}")
def delete_local_playlist(playlist_id: str, request: Request):
    _service(request).delete(playlist_id)
    return {"ok": True}


@router.post("/api/local-playlists/{playlist_id}/tracks")
def add_local_playlist_track(playlist_id: str, request: Request, body: dict = Body(...)):
    playlist = _handled(
        _service(request).add_track,
        playlist_id,
        name=body["name"],
        artist=body.get("artist", ""),
        album=body.get("album", ""),
        isrc=body.get("isrc", ""),
        duration_ms=body.get("duration_ms"),
        image=body.get("image", ""),
    )
    return asdict(playlist)


@router.delete("/api/local-playlists/{playlist_id}/tracks")
def remove_local_playlist_tracks(playlist_id: str, request: Request, body: dict = Body(...)):
    playlist = _handled(_service(request).remove_tracks, playlist_id, body["track_ids"])
    return asdict(playlist)


@router.post("/api/local-playlists/{playlist_id}/bind")
def bind_local_playlist(playlist_id: str, request: Request, body: dict = Body(...)):
    playlist = _handled(_service(request).bind, playlist_id, body["provider"], body.get("playlist_id"))
    return asdict(playlist)


@router.get("/api/local-playlists/{playlist_id}/compare/{provider}")
def compare_local_playlist(playlist_id: str, provider: str, request: Request):
    return _handled(_service(request).compare, playlist_id, provider)


@router.post("/api/local-playlists/{playlist_id}/pull/{provider}")
def pull_local_playlist(playlist_id: str, provider: str, request: Request, body: dict = Body(...)):
    playlist = _handled(_service(request).pull, playlist_id, provider, body["track_ids"])
    return asdict(playlist)


@router.post("/api/local-playlists/{playlist_id}/push/{provider}")
async def push_local_playlist(playlist_id: str, provider: str, request: Request, body: dict = Body(...)):
    # async so submit_push()'s asyncio.create_task has a running loop (a sync
    # endpoint runs in a threadpool with no loop and would 500).
    job = _handled(
        _service(request).submit_push,
        playlist_id,
        provider,
        execute=body.get("execute", False),
        allow_removals=body.get("allow_removals", False),
        max_removals=body.get("max_removals", 0),
    )
    return JSONResponse({"job_id": job["id"]}, status_code=202)
