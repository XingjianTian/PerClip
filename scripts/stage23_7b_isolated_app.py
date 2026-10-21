"""Disposable delayed app factory used only for first-load Android evidence."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

from fastapi.responses import JSONResponse
from perclip_ingest.main import create_app as create_perclip_app


def create_app():
    app = create_perclip_app()
    delay = max(0, int(os.environ.get("PERCLIP_SYNTHETIC_DELAY_MS", "0"))) / 1000
    data_dir = Path(os.environ.get("PERCLIP_DATA_DIR", "")).expanduser()
    inserted_during_list = False

    @app.middleware("http")
    async def synthetic_delay(request, call_next):
        nonlocal inserted_during_list
        if (
            request.url.path == "/api/knowledge/changes"
            and request.headers.get("x-perclip-synthetic-fail-changes") == "1"
        ):
            return JSONResponse({"ok": False, "message": "synthetic changes failure"}, status_code=503)
        if delay and request.url.path in {"/api/knowledge/clips", "/api/knowledge/summary"}:
            await asyncio.sleep(delay)
        response = await call_next(request)
        if (
            request.url.path == "/api/knowledge/clips"
            and request.headers.get("x-perclip-synthetic-insert-during-list") == "1"
            and not inserted_during_list
        ):
            inserted_during_list = True
            database_path = data_dir / "perclip.sqlite3"
            if database_path.is_file():
                with sqlite3.connect(database_path) as database:
                    database.execute(
                        "update clips set title_hint=title_hint || ' CONCURRENT-EVENT' where id=4"
                    )
        return response

    return app
