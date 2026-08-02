"""Read-only MCP adapter for birdframe's local analytical API."""
from __future__ import annotations

import json
import os
from typing import Literal
from urllib.parse import quote, urljoin

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from birdframe.config import Config


RankingMetric = Literal[
    "detections", "days", "first_heard", "earliest_time", "latest_time",
    "confidence", "rms_dbfs", "peak_dbfs", "snr_db",
]


class BirdframeAPI:
    def __init__(self, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        config = Config.load()
        self.base_url = (base_url or os.environ.get("BIRDFRAME_API_URL")
                         or f"http://localhost:{config.dashboard_port}").rstrip("/") + "/"
        self.transport = transport

    def get(self, path: str, **params) -> dict:
        clean = {key: value for key, value in params.items() if value is not None}
        try:
            with httpx.Client(base_url=self.base_url, transport=self.transport,
                              timeout=35.0) as client:
                response = client.get(path.lstrip("/"), params=clean)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("error", exc.response.text)
            except (ValueError, AttributeError):
                detail = exc.response.text
            raise ValueError(f"birdframe rejected the query: {detail}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"birdframe API is unavailable at {self.base_url}: {exc}") from exc

    def absolute_url(self, path: str | None) -> str | None:
        return urljoin(self.base_url, path.lstrip("/")) if path else None


def create_server(api: BirdframeAPI | None = None) -> FastMCP:
    api = api or BirdframeAPI()
    read_only = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False,
        idempotentHint=True, openWorldHint=False,
    )
    server = FastMCP(
        "birdframe",
        log_level="WARNING",
        instructions=(
            "Read-only access to birds heard by a private BirdNET installation. "
            "Counts are acoustic detection events/calls, not estimates of individual birds. "
            "Use rms_dbfs/peak_dbfs for loudness, snr_db for prominence above ambient sound, "
            "and confidence for classifier certainty. Reliability tiers are confirmed, probable, "
            "or tentative. Never describe a bird as visually seen."
        ),
    )

    @server.tool(annotations=read_only)
    def get_birds_now() -> dict:
        """Get the latest bird, recent realtime feed, and rolling soundscape."""
        return api.get("/api/now")

    @server.tool(annotations=read_only)
    def get_today() -> dict:
        """Get today's species, counts, times, reliability, and representative clips."""
        return api.get("/api/today")

    @server.tool(annotations=read_only)
    def query_detections(species: str | None = None,
                         start_day: str | None = None,
                         end_day: str | None = None,
                         min_confidence: float = 0.0,
                         before_id: int | None = None,
                         limit: int = 100) -> dict:
        """Query raw detection events newest-first. Dates use YYYY-MM-DD."""
        return api.get(
            "/api/detections", species=species, start_day=start_day, end_day=end_day,
            min_confidence=min_confidence, before_id=before_id, limit=limit,
        )

    @server.tool(annotations=read_only)
    def wait_for_detections(cursor: int, wait_seconds: float = 30.0,
                            species: str | None = None,
                            min_confidence: float = 0.0,
                            limit: int = 100) -> dict:
        """Wait up to 30 seconds for detections newer than a cursor.

        Start with the cursor returned by get_birds_now or query_detections,
        then pass next_cursor back on the next call.
        """
        return api.get(
            "/api/detections", after_id=cursor, wait=wait_seconds,
            species=species, min_confidence=min_confidence, limit=limit,
        )

    @server.tool(annotations=read_only)
    def rank_birds(metric: RankingMetric = "detections",
                   days: int | None = None,
                   start_day: str | None = None,
                   end_day: str | None = None,
                   tiers: str = "confirmed,probable,tentative",
                   min_confidence: float = 0.0,
                   limit: int = 20) -> dict:
        """Rank birds by frequency, active days, chronology, confidence, or sound.

        Use detections for 'most common/frequently heard', earliest_time for the
        earliest singer, rms_dbfs or peak_dbfs for loudest, and snr_db for the
        most prominent call over ambient sound.
        """
        return api.get(
            "/api/rankings", metric=metric, days=days, start_day=start_day,
            end_day=end_day, tiers=tiers, min_confidence=min_confidence, limit=limit,
        )

    @server.tool(annotations=read_only)
    def compare_periods(start_a: str, end_a: str, start_b: str, end_b: str,
                        tiers: str = "confirmed,probable,tentative",
                        min_confidence: float = 0.0,
                        limit: int = 20) -> dict:
        """Compare per-species detection counts between two YYYY-MM-DD ranges."""
        common = {"metric": "detections", "tiers": tiers,
                  "min_confidence": min_confidence, "limit": 100}
        period_a = api.get("/api/rankings", start_day=start_a, end_day=end_a, **common)
        period_b = api.get("/api/rankings", start_day=start_b, end_day=end_b, **common)
        a_by_name = {r["common_name"]: r for r in period_a["rankings"]}
        b_by_name = {r["common_name"]: r for r in period_b["rankings"]}
        changes = []
        for name in set(a_by_name) | set(b_by_name):
            a_count = a_by_name.get(name, {}).get("detections", 0)
            b_count = b_by_name.get(name, {}).get("detections", 0)
            changes.append({
                "common_name": name, "period_a_detections": a_count,
                "period_b_detections": b_count, "change": b_count - a_count,
            })
        changes.sort(key=lambda row: (-abs(row["change"]), row["common_name"]))
        return {
            "period_a": {"start_day": start_a, "end_day": end_a},
            "period_b": {"start_day": start_b, "end_day": end_b},
            "changes": changes[:max(1, min(limit, 100))],
            "count_semantics": "BirdNET detection events/calls, not individual birds",
        }

    @server.tool(annotations=read_only)
    def get_species(common_name: str, days: int | None = None) -> dict:
        """Get a species dossier: history, rhythms, confidence, clips, and companions."""
        return api.get(f"/api/species/{quote(common_name, safe='')}", days=days)

    @server.tool(annotations=read_only)
    def get_day(day: str) -> dict:
        """Get the complete field-journal record for one YYYY-MM-DD date."""
        return api.get(f"/api/day/{quote(day, safe='')}")

    @server.tool(annotations=read_only)
    def get_census() -> dict:
        """Get all-time totals, life list, daily counts, and hourly rhythms."""
        return api.get("/api/census")

    @server.tool(annotations=read_only)
    def get_best_clip(common_name: str) -> dict:
        """Get the URL of the retained best recording for a species."""
        species = api.get(f"/api/species/{quote(common_name, safe='')}")
        return {
            "common_name": common_name,
            "clip_url": api.absolute_url(species.get("clip_url")),
            "policy": "one highest-confidence clip per species/day is retained",
        }

    @server.resource("birdframe://now", mime_type="application/json")
    def now_resource() -> str:
        """Current listening state and realtime feed."""
        return json.dumps(api.get("/api/now"))

    @server.resource("birdframe://today", mime_type="application/json")
    def today_resource() -> str:
        """Today's reliability-assessed bird summary."""
        return json.dumps(api.get("/api/today"))

    @server.resource("birdframe://census", mime_type="application/json")
    def census_resource() -> str:
        """All-time bird census and life list."""
        return json.dumps(api.get("/api/census"))

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
