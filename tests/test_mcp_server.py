import asyncio
import json

import httpx

from birdframe.mcp_server import BirdframeAPI, create_server


def _transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/now":
        return httpx.Response(200, json={"cursor": 42, "latest": {"common_name": "Robin"}})
    if request.url.path == "/api/today":
        return httpx.Response(200, json={"date": "2026-07-20", "species": []})
    if request.url.path == "/api/census":
        return httpx.Response(200, json={"totals": {"detections": 12}})
    if request.url.path == "/api/rankings":
        return httpx.Response(200, json={
            "metric": request.url.params.get("metric"),
            "rankings": [{"common_name": "European Robin", "detections": 12}],
        })
    raise AssertionError(f"unexpected MCP API request: {request.url}")


def test_mcp_exposes_read_only_analysis_tools_and_resources():
    api = BirdframeAPI("http://birdframe.test", transport=httpx.MockTransport(_transport))
    server = create_server(api)

    async def inspect_server():
        tools = await server.list_tools()
        names = {tool.name for tool in tools}
        assert {"get_birds_now", "query_detections", "wait_for_detections",
                "rank_birds", "compare_periods", "get_species", "get_day",
                "get_census", "get_best_clip"} <= names
        assert not ({"post", "generate", "settings"} & names)
        assert all(tool.annotations.readOnlyHint is True for tool in tools)
        result = await server.call_tool("rank_birds", {"metric": "detections"})
        assert json.loads(result[0].text)["rankings"][0]["common_name"] == "European Robin"
        resources = {str(resource.uri) for resource in await server.list_resources()}
        assert {"birdframe://now", "birdframe://today", "birdframe://census"} <= resources
        content = list(await server.read_resource("birdframe://now"))
        assert json.loads(content[0].content)["cursor"] == 42

    asyncio.run(inspect_server())
