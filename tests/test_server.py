"""The tools, called through the MCP SDK's in-process client."""

import json

import httpx
import pytest
import respx
import synth
from mcp import Client

from figma_fit.figma import API_BASE, FigmaClient
from figma_fit.server import create_server
from figma_fit.tokens import estimate

pytestmark = pytest.mark.anyio

URL = "https://www.figma.com/design/FileKey/Shop?node-id=12-1"
NODES_URL = f"{API_BASE}/v1/files/FileKey/nodes"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_server():
    return create_server(lambda: FigmaClient("test-token"))


def text_of(result):
    assert len(result.content) == 1
    return result.content[0].text


async def test_lists_exactly_two_tools():
    async with Client(make_server()) as client:
        tools = await client.list_tools()
    assert sorted(t.name for t in tools.tools) == [
        "fetch_node_within_budget",
        "fetch_within_budget",
    ]


@respx.mock
async def test_fetch_within_budget_returns_report_and_data(pricing_body):
    respx.get(NODES_URL).mock(return_value=httpx.Response(200, json=pricing_body))
    async with Client(make_server()) as client:
        result = await client.call_tool("fetch_within_budget", {"url": URL, "budget": 5000})
    assert not result.is_error
    text = text_of(result)
    line, body = text.split("\n", 1)
    assert line.startswith("figma-fit: ")
    assert json.loads(body)["data"][0]["name"] == "Pricing"
    assert estimate(text) <= 5000


@respx.mock
async def test_split_plan_follow_up_is_served_from_cache():
    doc = synth.make_frame(5, sections=12, rows=20)
    body = {"name": "Big", "version": "7", "nodes": {doc["id"]: {"document": doc}}}
    route = respx.get(NODES_URL).mock(return_value=httpx.Response(200, json=body))
    url = f"https://www.figma.com/design/FileKey/Big?node-id={doc['id'].replace(':', '-')}"
    budget = 3000

    async with Client(make_server()) as client:
        first = await client.call_tool("fetch_within_budget", {"url": url, "budget": budget})
        plan = json.loads(text_of(first).split("\n", 1)[1])
        assert plan["status"] == "split"
        call = plan["calls"][0]
        follow = await client.call_tool(
            "fetch_node_within_budget",
            {"file_key": "FileKey", "node_ids": call["node_ids"], "budget": budget},
        )

    assert route.call_count == 1
    text = text_of(follow)
    assert estimate(text) <= budget
    data = json.loads(text.split("\n", 1)[1])
    assert data["status"] == "fit"
    assert [n["id"] for n in data["data"]] == call["node_ids"]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"url": "https://www.figma.com/board/abc/x?node-id=1-2"}, "FigJam"),
        ({"url": "https://www.figma.com/design/abc/x"}, "node-id"),
        ({"url": URL, "passes": ["nope"]}, "unknown pass"),
    ],
)
@respx.mock(assert_all_called=False)
async def test_bad_input_is_an_actionable_tool_error(args, message):
    route = respx.get(NODES_URL)
    async with Client(make_server()) as client:
        result = await client.call_tool("fetch_within_budget", args)
    assert result.is_error
    assert message in text_of(result)
    assert route.call_count == 0  # rejected before spending a rate-limited request


async def test_budget_below_minimum_is_rejected_by_schema():
    async with Client(make_server()) as client:
        result = await client.call_tool("fetch_within_budget", {"url": URL, "budget": 10})
    assert result.is_error


@respx.mock
async def test_rate_limit_message_says_not_to_loop():
    respx.get(NODES_URL).mock(
        return_value=httpx.Response(429, json={"err": "Rate limit"}, headers={"Retry-After": "60"})
    )
    async with Client(make_server()) as client:
        result = await client.call_tool("fetch_within_budget", {"url": URL})
    assert result.is_error
    assert "Retry after 60s" in text_of(result)
    assert "Do not retry in a loop" in text_of(result)


async def test_missing_token_explains_what_to_set(monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    monkeypatch.delenv("FIGMA_API_KEY", raising=False)
    async with Client(create_server()) as client:
        result = await client.call_tool("fetch_within_budget", {"url": URL})
    assert result.is_error
    assert "FIGMA_TOKEN" in text_of(result)
