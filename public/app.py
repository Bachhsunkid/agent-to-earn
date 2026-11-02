"""Public status page: static files, the operator's site config and the sanitized snapshot.

Runs in its own container with no secrets and no route to the bot (compose network `edge`).
The dashboard writes the snapshot (dashboard/public_snapshot.py); this app only reads it.
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
SNAPSHOT = Path(os.environ.get("PUBLIC_DATA", "/data")) / "snapshot.json"
SITE = HERE / "site.json"
SITE_EXAMPLE = HERE / "site.example.json"

SECURITY_HEADERS = {
    # Google Fonts serves only CSS and font files; scripts stay first-party.
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
                                "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
                                "manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

app = FastAPI(title="agent-to-earn public", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    # Without it browsers cache the page heuristically for hours and mix old HTML/JS after a deploy.
    # no-cache revalidates by ETag, so an unchanged file still costs only a 304.
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


@app.get("/api/snapshot.json")
def snapshot() -> JSONResponse:
    data = read_json(SNAPSHOT)
    if data is None:
        return JSONResponse({"error": "no snapshot yet"}, status_code=503, headers={"Cache-Control": "no-store"})
    return JSONResponse(data, headers={"Cache-Control": "public, max-age=30"})


@app.get("/api/site.json")
def site() -> JSONResponse:
    data = read_json(SITE) if SITE.exists() else read_json(SITE_EXAMPLE)
    return JSONResponse(data or {}, headers={"Cache-Control": "public, max-age=300"})


app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
