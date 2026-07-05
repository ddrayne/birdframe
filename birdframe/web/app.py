"""Local dashboard: JSON API + a single-page UI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

STATIC = Path(__file__).resolve().parent / "static"

# Settings exposed in the dashboard, grouped for display. Keys must exist in
# config.DEFAULTS. Changes to keys in RESTART_REQUIRED only take effect when the
# app restarts (they configure objects built once at startup); everything else
# is applied to the running app immediately.
EDITABLE_SETTINGS = [
    ("Posting", ["post_mode", "post_time"]),
    ("Live mode", ["live_min_gap_minutes", "live_window_start", "live_window_end"]),
    ("Cost controls", ["min_species_for_image", "max_paid_images_per_day"]),
    ("Frame", ["frame_url", "frame_hold_minutes", "frame_saturation"]),
    ("Style", ["style_mode", "pinned_style"]),
    ("Detection", ["confidence_threshold", "input_device"]),
    ("Image", ["openai_model", "image_quality"]),
]
RESTART_REQUIRED = {
    "confidence_threshold", "input_device", "openai_model", "image_quality",
    "latitude", "longitude", "geo_floor", "chunk_seconds",
    "chunk_overlap_seconds", "dashboard_port",
}


@dataclass
class AppContext:
    store: object
    artist: object
    publisher: object
    now: Callable[[], datetime] = datetime.now
    config: object = None
    apply_settings: Callable[[], None] = None


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
        # Explicit user action → force a real (paid) image if a key is set.
        rec = ctx.artist.generate(ctx.now(), force_paid=True)
        result = _publish(ctx, rec)
        return {"image_id": rec.id, "publish": result.status, "detail": result.detail}

    @app.post("/api/repost/{image_id}")
    def repost(image_id: int):
        rec = ctx.store.get_image(image_id)
        if rec is None:
            return JSONResponse({"error": "no such image"}, status_code=404)
        result = _publish(ctx, rec)
        return {"image_id": rec.id, "publish": result.status, "detail": result.detail}

    @app.get("/api/settings")
    def get_settings():
        cfg = ctx.config
        groups = [
            {"group": group,
             "fields": [{"key": k, "value": getattr(cfg, k),
                         "restart": k in RESTART_REQUIRED} for k in keys]}
            for group, keys in EDITABLE_SETTINGS
        ]
        return {"groups": groups}

    @app.post("/api/settings")
    async def post_settings(request: Request):
        cfg = ctx.config
        body = await request.json()
        editable = {k for _, keys in EDITABLE_SETTINGS for k in keys}
        saved, restart, errors = [], [], {}
        for key, raw in body.items():
            if key not in editable:
                errors[key] = "not an editable setting"
                continue
            try:
                current = getattr(cfg, key)
                coerced = type(current)(raw) if not isinstance(current, bool) else bool(raw)
            except (TypeError, ValueError):
                errors[key] = f"expected {type(getattr(cfg, key)).__name__}"
                continue
            setattr(cfg, key, coerced)
            saved.append(key)
            if key in RESTART_REQUIRED:
                restart.append(key)
        if errors:
            return JSONResponse({"error": "invalid settings", "fields": errors},
                                status_code=400)
        cfg.save()
        if ctx.apply_settings:
            ctx.apply_settings()   # push live-applicable changes onto running objects
        return {"saved": saved, "restart_required": restart}

    return app


def _publish(ctx: AppContext, rec):
    with open(rec.path, "rb") as fh:
        result = ctx.publisher.publish(fh.read())
    if result.status == "posted":
        ctx.store.mark_posted(rec.id, ctx.now())
    return result
