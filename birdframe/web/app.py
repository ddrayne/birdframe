"""Local dashboard: JSON API + a single-page UI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

STATIC = Path(__file__).resolve().parent / "static"


@dataclass
class AppContext:
    store: object
    artist: object
    publisher: object
    now: Callable[[], datetime] = datetime.now


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="birdframe")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/today")
    def today():
        now = ctx.now()
        species = ctx.store.species_for_day(now)
        return {
            "date": now.strftime("%Y-%m-%d"),
            "species": [
                {"common_name": s.common_name, "scientific_name": s.scientific_name,
                 "count": s.count, "first_heard": s.first_heard.strftime("%H:%M"),
                 "last_heard": s.last_heard.strftime("%H:%M"),
                 "peak_hour": s.peak_hour, "best_confidence": round(s.best_confidence, 2)}
                for s in species
            ],
        }

    @app.get("/api/history")
    def history():
        rows = ctx.store.recent_images(limit=100)
        return {"images": [
            {"id": r.id, "generated_at": r.generated_at.isoformat(), "style": r.style,
             "species": r.species,
             "posted_at": r.posted_at.isoformat() if r.posted_at else None}
            for r in rows
        ]}

    @app.get("/api/image/{image_id}")
    def image(image_id: int):
        rec = ctx.store.get_image(image_id)
        if rec is None or not Path(rec.path).exists():
            return JSONResponse({"error": "no such image"}, status_code=404)
        return FileResponse(rec.path, media_type="image/png")

    @app.post("/api/post-now")
    def post_now():
        rec = ctx.artist.generate(ctx.now())
        result = _publish(ctx, rec)
        return {"image_id": rec.id, "publish": result.status, "detail": result.detail}

    @app.post("/api/repost/{image_id}")
    def repost(image_id: int):
        rec = ctx.store.get_image(image_id)
        if rec is None:
            return JSONResponse({"error": "no such image"}, status_code=404)
        result = _publish(ctx, rec)
        return {"image_id": rec.id, "publish": result.status, "detail": result.detail}

    return app


def _publish(ctx: AppContext, rec):
    with open(rec.path, "rb") as fh:
        result = ctx.publisher.publish(fh.read())
    if result.status == "posted":
        ctx.store.mark_posted(rec.id, ctx.now())
    return result
