import copy

import httpx
import pytest
import respx

from figma_fit.figma import (
    API_BASE,
    FigmaAPIError,
    FigmaAuthError,
    FigmaClient,
    FigmaNotFoundError,
    FigmaRateLimitError,
)
from figma_fit.url import FigmaRef

NODES_URL = f"{API_BASE}/v1/files/FileKey/nodes"
REF = FigmaRef("FileKey", "12:1")


@pytest.fixture
def client():
    with FigmaClient("test-token") as c:
        yield c


@respx.mock
def test_fetches_node_subtree(client, pricing_body):
    route = respx.get(NODES_URL).mock(return_value=httpx.Response(200, json=pricing_body))

    fetched = client.fetch_node(REF)

    request = route.calls.last.request
    assert request.headers["X-Figma-Token"] == "test-token"
    assert request.url.params["ids"] == "12:1"
    assert "geometry" not in request.url.params
    assert fetched.document["name"] == "Pricing"
    assert fetched.file_name == "Fixture Shop"
    assert fetched.version == "2219874123"
    assert "3:10" in fetched.components
    assert "3:9" in fetched.component_sets
    assert fetched.from_cache is False


@respx.mock
def test_second_fetch_of_same_node_makes_no_http_call(client, pricing_body):
    route = respx.get(NODES_URL).mock(return_value=httpx.Response(200, json=pricing_body))

    client.fetch_node(REF)
    again = client.fetch_node(REF)

    assert route.call_count == 1
    assert again.from_cache is True
    assert again.document["name"] == "Pricing"


@respx.mock
def test_descendant_is_served_from_cached_ancestor(client, pricing_body):
    route = respx.get(NODES_URL).mock(return_value=httpx.Response(200, json=pricing_body))

    client.fetch_node(REF)
    card = client.fetch_node(FigmaRef("FileKey", "12:7"))
    sublayer = client.fetch_node(FigmaRef("FileKey", "I12:7;3:11"))

    assert route.call_count == 1
    assert card.node_id == "12:7"
    assert card.document["componentProperties"]["Tier"]["value"] == "Pro"
    assert sublayer.document["characters"] == "$29"
    assert card.version == "2219874123"


@respx.mock
def test_refresh_bypasses_cache(client, pricing_body):
    route = respx.get(NODES_URL).mock(return_value=httpx.Response(200, json=pricing_body))

    client.fetch_node(REF)
    client.fetch_node(REF, refresh=True)

    assert route.call_count == 2


@respx.mock
def test_new_file_version_evicts_older_cached_subtrees(client, pricing_body):
    newer = copy.deepcopy(pricing_body)
    newer["version"] = "2219874999"
    newer["nodes"]["12:1"]["document"]["children"][2]["children"][1]["children"][0][
        "characters"
    ] = "$39"
    respx.get(NODES_URL).mock(
        side_effect=[httpx.Response(200, json=pricing_body), httpx.Response(200, json=newer)]
    )

    client.fetch_node(REF)
    client.fetch_node(REF, refresh=True)
    price = client.fetch_node(FigmaRef("FileKey", "I12:7;3:11"))

    assert price.from_cache and price.version == "2219874999"
    assert price.document["characters"] == "$39"


@respx.mock
def test_cache_is_per_file(client, pricing_body):
    respx.get(NODES_URL).mock(return_value=httpx.Response(200, json=pricing_body))
    other = respx.get(f"{API_BASE}/v1/files/OtherKey/nodes").mock(
        return_value=httpx.Response(200, json={"nodes": {"12:1": {"document": {"id": "12:1"}}}})
    )

    client.fetch_node(REF)
    client.fetch_node(FigmaRef("OtherKey", "12:1"))

    assert other.call_count == 1


@respx.mock
def test_missing_node_raises_not_found(client):
    respx.get(NODES_URL).mock(return_value=httpx.Response(200, json={"nodes": {"12:1": None}}))
    with pytest.raises(FigmaNotFoundError):
        client.fetch_node(REF)


@respx.mock
@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (403, {"status": 403, "err": "Invalid token"}, FigmaAuthError),
        (404, {"status": 404, "err": "Not found"}, FigmaNotFoundError),
        (500, {"status": 500, "err": "Internal"}, FigmaAPIError),
    ],
)
def test_http_errors_map_to_exceptions(client, status, body, error):
    respx.get(NODES_URL).mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(error, match=body["err"]):
        client.fetch_node(REF)


@respx.mock
def test_rate_limit_surfaces_retry_after_without_retrying(client):
    route = respx.get(NODES_URL).mock(
        return_value=httpx.Response(
            429, json={"status": 429, "err": "Rate limit exceeded"}, headers={"Retry-After": "120"}
        )
    )
    with pytest.raises(FigmaRateLimitError) as excinfo:
        client.fetch_node(REF)
    assert excinfo.value.retry_after == 120
    assert route.call_count == 1


@respx.mock
def test_failed_fetch_is_not_cached(client, pricing_body):
    route = respx.get(NODES_URL).mock(
        side_effect=[httpx.Response(500, text="boom"), httpx.Response(200, json=pricing_body)]
    )
    with pytest.raises(FigmaAPIError, match="boom"):
        client.fetch_node(REF)
    assert client.fetch_node(REF).document["name"] == "Pricing"
    assert route.call_count == 2


def test_from_env_reads_token(monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    monkeypatch.setenv("FIGMA_API_KEY", "from-env")
    with FigmaClient.from_env() as c:
        assert c._headers["X-Figma-Token"] == "from-env"


def test_from_env_without_token_explains_what_to_set(monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    monkeypatch.delenv("FIGMA_API_KEY", raising=False)
    with pytest.raises(FigmaAuthError, match="FIGMA_TOKEN"):
        FigmaClient.from_env()
