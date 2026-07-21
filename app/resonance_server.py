from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

ROOT = Path(
    os.environ.get(
        "RESONANCE_ROOT",
        str(Path(__file__).resolve().parents[1]),
    )
).resolve()

ARBITER_EMBED_URL = os.environ.get(
    "ARBITER_EMBED_URL",
    "http://127.0.0.1:8000/v1/embed",
)

SAFE_EXTENSIONS = {
    ".html",
    ".css",
    ".js",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
}

app = FastAPI(
    title="RESONANCE",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def html_file(path: Path) -> FileResponse:
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "resonance",
            "catalogues": {
                "hidden_gem_lightcast": 315,
                "angel": 124,
            },
            "embed": ARBITER_EMBED_URL,
        }
    )


@app.post("/v1/embed")
async def embed_query(request: Request) -> Response:
    raw_request = await request.body()

    if len(raw_request) > 100_000:
        return JSONResponse(
            {"detail": "Request is too large."},
            status_code=413,
        )

    try:
        incoming = json.loads(raw_request)
    except json.JSONDecodeError:
        return JSONResponse(
            {"detail": "Invalid JSON."},
            status_code=400,
        )

    texts = incoming.get("texts") if isinstance(incoming, dict) else None

    # The live catalogue is already embedded. Runtime accepts one query only.
    if (
        not isinstance(texts, list)
        or len(texts) != 1
        or not isinstance(texts[0], str)
        or not texts[0].strip()
    ):
        return JSONResponse(
            {"detail": "Exactly one non-empty query is required."},
            status_code=400,
        )

    if len(texts[0]) > 20_000:
        return JSONResponse(
            {"detail": "Query is too long."},
            status_code=413,
        )

    upstream_payload = json.dumps(
        {
            "texts": [texts[0]],
            "use_freq": True,
        }
    ).encode("utf-8")

    upstream_request = urllib.request.Request(
        ARBITER_EMBED_URL,
        data=upstream_payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(upstream_request, timeout=45) as upstream:
            content = upstream.read()
            content_type = (
                upstream.headers.get_content_type()
                if upstream.headers
                else "application/json"
            )
            return Response(
                content=content,
                status_code=upstream.status,
                media_type=content_type,
                headers={"Cache-Control": "no-store"},
            )
    except urllib.error.HTTPError as error:
        return Response(
            content=error.read(),
            status_code=error.code,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as error:
        return JSONResponse(
            {
                "detail": "Local ARBITER embed service is unavailable.",
                "error": str(error),
            },
            status_code=502,
        )


@app.get("/")
def hidden_gem_home() -> FileResponse:
    return html_file(ROOT / "index.html")


@app.get("/angel")
@app.get("/angel/")
def angel_home() -> FileResponse:
    return html_file(ROOT / "angel" / "index.html")


@app.get("/{asset_path:path}")
def static_asset(asset_path: str) -> FileResponse:
    relative = Path(asset_path)

    if any(part.startswith(".") for part in relative.parts):
        raise HTTPException(status_code=404)

    candidate = (ROOT / relative).resolve()

    if candidate != ROOT and ROOT not in candidate.parents:
        raise HTTPException(status_code=404)

    if candidate.is_dir():
        candidate = candidate / "index.html"

    if not candidate.is_file():
        raise HTTPException(status_code=404)

    if candidate.suffix.lower() not in SAFE_EXTENSIONS:
        raise HTTPException(status_code=404)

    media_type, _ = mimetypes.guess_type(candidate.name)
    cache = (
        "no-cache"
        if candidate.suffix.lower() == ".html"
        else "public, max-age=86400"
    )

    return FileResponse(
        candidate,
        media_type=media_type,
        headers={"Cache-Control": cache},
    )
