"""Local dashboard: JSON API + a single-page UI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import quote

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
    ("Live", ["capture_window_minutes"]),
    ("Frame", ["frame_url", "frame_hold_minutes", "frame_saturation"]),
    ("Style", ["style_mode", "pinned_style"]),
    ("Detection", ["confidence_threshold", "min_species_confidence", "input_device"]),
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
    styles_dir: object = None
    preview_dir: object = None
    geo_lookup: object = None       # dict {scientific_name: plausibility} for reliability
    runtime: object = None          # live daemon state (health, listening status)


def _assess_species(ctx, s, day=None):
    """Attach a reliability assessment to a SpeciesDay for honest presentation."""
    from birdframe.reliability import GEO_DEFAULT, assess
    geo = GEO_DEFAULT
    if ctx.geo_lookup:
        geo = ctx.geo_lookup.get(s.scientific_name, GEO_DEFAULT)
    a = assess(s.best_confidence, geo, s.count)
    has_clip = bool(day and ctx.store.clip_path(day, s.common_name))
    return {
        "common_name": s.common_name, "scientific_name": s.scientific_name,
        "count": s.count, "best_confidence": round(s.best_confidence, 2),
        "first_heard": s.first_heard.strftime("%H:%M"),
        "last_heard": s.last_heard.strftime("%H:%M"), "peak_hour": s.peak_hour,
        "tier": a.tier, "reliability": a.score, "reasons": a.reasons,
        "geo": round(geo, 3), "has_clip": has_clip,
        "clip_url": f"/api/clip/{day}/{quote(s.common_name)}" if has_clip else None,
    }


def create_app(ctx: AppContext) -> FastAPI:
    import threading as _threading
    app = FastAPI(title="birdframe")

    _capture = {"state": "idle", "cancel": False, "result": None,
                "species": [], "lock": _threading.Lock()}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    # ---- PWA: installable to the dock / home screen ----
    @app.get("/manifest.webmanifest")
    def manifest():
        return JSONResponse({
            "name": "birdframe", "short_name": "birdframe",
            "description": "Birds heard at the window in Edinburgh",
            "start_url": "/", "display": "standalone",
            "background_color": "#14170F", "theme_color": "#2E6A4F",
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png",
                 "purpose": "any maskable"},
            ],
        }, media_type="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(STATIC / "sw.js", media_type="text/javascript")

    def _icon(size: int) -> bytes:
        from birdframe.icon import render_icon
        return render_icon(size)

    @app.get("/icon-192.png")
    def icon192():
        from fastapi.responses import Response
        return Response(_icon(192), media_type="image/png")

    @app.get("/icon-512.png")
    def icon512():
        from fastapi.responses import Response
        return Response(_icon(512), media_type="image/png")

    # ---- Wikipedia enrichment (proxied + cached to be kind to their API) ----
    _wiki_cache: dict[str, dict] = {}

    @app.get("/api/bird/{scientific_name}")
    def bird_info(scientific_name: str):
        import httpx
        key = scientific_name.strip()
        if key in _wiki_cache:
            return _wiki_cache[key]
        info = {"title": key, "extract": "", "thumbnail": None,
                "url": f"https://en.wikipedia.org/wiki/{key.replace(' ', '_')}"}
        try:
            r = httpx.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/"
                + key.replace(" ", "_"),
                headers={"User-Agent": "birdframe/1.0 (bird dashboard)"},
                timeout=6, follow_redirects=True)
            if r.status_code == 200:
                d = r.json()
                info["title"] = d.get("title", key)
                info["extract"] = d.get("extract", "")
                info["url"] = d.get("content_urls", {}).get("desktop", {}).get("page", info["url"])
                thumb = d.get("thumbnail", {})
                info["thumbnail"] = thumb.get("source")
        except Exception:
            pass
        _wiki_cache[key] = info
        return info

    def _conf_floor() -> float:
        return float(getattr(ctx.config, "min_species_confidence", 0.0) or 0.0)

    _TIER_ORDER = {"confirmed": 0, "probable": 1, "tentative": 2}

    @app.get("/api/today")
    def today():
        now = ctx.now()
        day = now.strftime("%Y-%m-%d")
        species = ctx.store.species_for_day(now, min_confidence=_conf_floor())
        assessed = [_assess_species(ctx, s, day) for s in species]
        assessed.sort(key=lambda x: (_TIER_ORDER[x["tier"]], -x["count"]))
        return {"date": day, "species": assessed}

    @app.get("/api/clip/{day}/{common_name}")
    def clip(day: str, common_name: str):
        path = ctx.store.clip_path(day, common_name)
        if not path or not Path(path).exists():
            return JSONResponse({"error": "no clip"}, status_code=404)
        return FileResponse(path, media_type="audio/ogg")

    @app.get("/api/now")
    def now_listening():
        """The live listening view: the most recent bird, a streaming feed of
        recent detections, and a rolling summary of the current soundscape."""
        now = ctx.now()
        floor = _conf_floor()
        window_min = getattr(ctx.config, "capture_window_minutes", 60)
        recent = ctx.store.recent_detections(limit=40, min_confidence=floor)
        window = ctx.store.species_in_window(now - timedelta(minutes=window_min), now,
                                             min_confidence=floor)
        today = ctx.store.species_for_day(now, min_confidence=floor)
        first_ever = ctx.store.first_ever_on_day(now)
        latest = recent[0] if recent else None
        day = now.strftime("%Y-%m-%d")
        window_assessed = [_assess_species(ctx, s, day) for s in window]
        window_assessed.sort(key=lambda x: (_TIER_ORDER[x["tier"]], -x["count"]))
        # tier of the most-recent bird, from its window/day track record
        latest_tier = None
        if latest is not None:
            match = next((w for w in window_assessed if w["scientific_name"] == latest.scientific_name), None)
            if match is None:
                from birdframe.reliability import GEO_DEFAULT, assess
                geo = (ctx.geo_lookup or {}).get(latest.scientific_name, GEO_DEFAULT)
                match = {"tier": assess(latest.confidence, geo, 1).tier}
            latest_tier = match["tier"]
        return {
            "now": now.strftime("%H:%M:%S"),
            "window_minutes": window_min,
            "latest": None if latest is None else {
                "common_name": latest.common_name,
                "scientific_name": latest.scientific_name,
                "confidence": round(latest.confidence, 2),
                "at": latest.timestamp.strftime("%H:%M:%S"),
                "seconds_ago": max(0, int((now - latest.timestamp).total_seconds())),
                "tier": latest_tier,
                "clip_url": (f"/api/clip/{day}/{quote(latest.common_name)}"
                             if ctx.store.clip_path(day, latest.common_name) else None),
            },
            "feed": [
                {"common_name": d.common_name, "scientific_name": d.scientific_name,
                 "confidence": round(d.confidence, 2), "at": d.timestamp.strftime("%H:%M:%S")}
                for d in recent
            ],
            "window_species": window_assessed,
            "activity": ctx.store.activity_buckets(
                now - timedelta(minutes=window_min), now, n=24, min_confidence=floor),
            "today_species_count": len(today),
            "new_today": sorted(first_ever),
        }

    @app.post("/api/capture")
    def capture():
        """Capture the birds heard in the recent live window into a picture, in
        the background (gpt-image takes ~2 min). Cancellable via /api/capture/cancel."""
        import threading
        with _capture["lock"]:
            if _capture["state"] == "running":
                return {"status": "running"}
            _capture.update(state="running", cancel=False, result=None, species=[])

        now = ctx.now()
        window_min = getattr(ctx.config, "capture_window_minutes", 60)
        species = ctx.store.species_in_window(now - timedelta(minutes=window_min), now,
                                              min_confidence=_conf_floor())

        def _run():
            try:
                rec = ctx.artist.generate(now, force_paid=True, species_days=species)
                if rec is None:
                    with _capture["lock"]:
                        _capture.update(state="empty", species=[])
                    return
                with _capture["lock"]:
                    if _capture["cancel"]:
                        _capture.update(state="cancelled", species=rec.species)
                        return
                result = _publish(ctx, rec, force=True)
                with _capture["lock"]:
                    _capture.update(state="done", result=result.status, species=rec.species)
            except Exception as exc:  # noqa: BLE001
                with _capture["lock"]:
                    _capture.update(state="error", result=str(exc))

        threading.Thread(target=_run, daemon=True).start()
        return {"status": "started", "window_minutes": window_min,
                "species": [s.common_name for s in species]}

    @app.post("/api/capture/cancel")
    def capture_cancel():
        """Stop the current capture — the image won't be sent to the frame."""
        with _capture["lock"]:
            if _capture["state"] == "running":
                _capture["cancel"] = True
                return {"status": "cancelling"}
            return {"status": _capture["state"]}

    @app.get("/api/capture/status")
    def capture_status():
        with _capture["lock"]:
            return {"state": _capture["state"], "result": _capture["result"],
                    "species": _capture["species"]}

    @app.post("/api/block")
    async def block_species(request: Request):
        """Veto a species as 'not here': stop detecting it and purge its history."""
        body = await request.json()
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse({"error": "name required"}, status_code=400)
        blocked = list(getattr(ctx.config, "blocked_species", []) or [])
        if name not in blocked:
            blocked.append(name)
        ctx.config.blocked_species = blocked
        ctx.config.save()
        if ctx.apply_settings:
            ctx.apply_settings()
        removed = ctx.store.delete_species(name)
        return {"blocked": name, "removed_detections": removed}

    @app.post("/api/unblock")
    async def unblock_species(request: Request):
        body = await request.json()
        name = (body.get("name") or "").strip()
        blocked = [b for b in (getattr(ctx.config, "blocked_species", []) or []) if b != name]
        ctx.config.blocked_species = blocked
        ctx.config.save()
        if ctx.apply_settings:
            ctx.apply_settings()
        return {"blocked_species": blocked}

    @app.get("/api/blocked")
    def blocked_species():
        return {"blocked_species": list(getattr(ctx.config, "blocked_species", []) or [])}

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
        # Explicit user action → force a real (paid) image and override any hold.
        rec = ctx.artist.generate(ctx.now(), force_paid=True)
        if rec is None:
            return {"skipped": True, "reason": "no birds heard today yet — nothing to picture"}
        result = _publish(ctx, rec, force=True)
        return {"image_id": rec.id, "publish": result.status, "detail": result.detail}

    @app.post("/api/repost/{image_id}")
    def repost(image_id: int):
        rec = ctx.store.get_image(image_id)
        if rec is None:
            return JSONResponse({"error": "no such image"}, status_code=404)
        result = _publish(ctx, rec, force=True)
        return {"image_id": rec.id, "publish": result.status, "detail": result.detail}

    # ---- Styles editor ----
    import threading

    from birdframe import styles as stylemod
    from birdframe.rollup import build_prompt

    _preview_jobs: dict[str, str] = {}
    _preview_lock = threading.Lock()

    def _reload_styles():
        if ctx.styles_dir and hasattr(ctx.artist, "styles"):
            ctx.artist.styles = stylemod.load_styles(ctx.styles_dir)

    def _is_pinned(name: str) -> bool:
        cfg = ctx.config
        return bool(cfg and cfg.style_mode == "pinned" and cfg.pinned_style == name)

    def _preview_path(slug: str):
        return Path(ctx.preview_dir) / f"{slug}.png" if ctx.preview_dir else None

    @app.get("/api/styles")
    def list_styles():
        items = []
        for s in stylemod.load_styles(ctx.styles_dir):
            pp = _preview_path(s.name)
            items.append({
                "name": s.name, "prompt": s.prompt, "avoid": s.avoid,
                "pinned": _is_pinned(s.name),
                "has_preview": bool(pp and pp.exists()),
                "sample_prompt": build_prompt(s, stylemod.SAMPLE_SCENE),
            })
        return {"styles": items, "sample_scene": stylemod.SAMPLE_SCENE,
                "key_set": getattr(ctx.artist, "image_client", None) is not None}

    @app.put("/api/styles/{name}")
    async def save_style_ep(name: str, request: Request):
        body = await request.json()
        try:
            slug = stylemod.save_style(ctx.styles_dir, body.get("name", name),
                                       body.get("prompt", ""), body.get("avoid", ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        _reload_styles()
        return {"saved": slug}

    @app.delete("/api/styles/{name}")
    def delete_style_ep(name: str):
        if len(stylemod.load_styles(ctx.styles_dir)) <= 1:
            return JSONResponse({"error": "can't delete the last style"}, status_code=400)
        ok = stylemod.delete_style(ctx.styles_dir, name)
        pp = _preview_path(stylemod.slugify(name))
        if pp and pp.exists():
            pp.unlink()
        _reload_styles()
        return {"deleted": ok}

    @app.post("/api/styles/{name}/pin")
    def pin_style(name: str):
        style = stylemod.get_style(ctx.styles_dir, name)
        if style is None:
            return JSONResponse({"error": "no such style"}, status_code=404)
        ctx.config.style_mode = "pinned"
        ctx.config.pinned_style = style.name
        ctx.config.save()
        if ctx.apply_settings:
            ctx.apply_settings()
        return {"pinned": style.name}

    @app.post("/api/styles/unpin")
    def unpin_style():
        ctx.config.style_mode = "rotate"
        ctx.config.save()
        if ctx.apply_settings:
            ctx.apply_settings()
        return {"mode": "rotate"}

    @app.post("/api/styles/{name}/preview")
    def make_preview(name: str):
        style = stylemod.get_style(ctx.styles_dir, name)
        if style is None:
            return JSONResponse({"error": "no such style"}, status_code=404)
        client = getattr(ctx.artist, "image_client", None)
        if client is None:
            return JSONResponse(
                {"error": "set an OpenAI key (birdframe set-key) to generate previews"},
                status_code=400)
        slug = style.name
        with _preview_lock:
            if slug in _preview_jobs:
                return {"status": "generating", "name": slug}
            _preview_jobs[slug] = "generating"

        prompt = build_prompt(style, stylemod.SAMPLE_SCENE)

        def _run():
            try:
                art = client.generate(prompt)
                pp = _preview_path(slug)
                pp.parent.mkdir(parents=True, exist_ok=True)
                pp.write_bytes(art)
                with _preview_lock:
                    _preview_jobs[slug] = "done"
            except Exception as exc:  # noqa: BLE001
                with _preview_lock:
                    _preview_jobs[slug] = f"error: {exc}"

        # gpt-image generation takes ~2 min — never block the request on it.
        threading.Thread(target=_run, daemon=True).start()
        return {"status": "started", "name": slug}

    @app.get("/api/styles/{name}/preview-status")
    def preview_status(name: str):
        slug = stylemod.slugify(name)
        pp = _preview_path(slug)
        with _preview_lock:
            state = _preview_jobs.get(slug)
        if pp and pp.exists() and state != "generating":
            return {"status": "ready"}
        if state == "generating":
            return {"status": "generating"}
        if state and state.startswith("error"):
            return {"status": "error", "detail": state}
        return {"status": "none"}

    @app.get("/api/styles/{name}/preview.png")
    def get_preview(name: str):
        pp = _preview_path(stylemod.slugify(name))
        if not pp or not pp.exists():
            return JSONResponse({"error": "no preview yet"}, status_code=404)
        return FileResponse(pp, media_type="image/png")

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


def _publish(ctx: AppContext, rec, force: bool = False):
    with open(rec.path, "rb") as fh:
        result = ctx.publisher.publish(fh.read(), force=force)
    if result.status == "posted":
        ctx.store.mark_posted(rec.id, ctx.now())
    return result
