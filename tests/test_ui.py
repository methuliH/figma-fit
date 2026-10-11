import json
import threading

import httpx
import pytest
import respx

from figma_fit.figma import API_BASE, FigmaAuthError, FigmaClient
from figma_fit.ui import KEY_HEADER, App, make_server

LINK = "https://www.figma.com/design/FileKey/Shop?node-id=12-1"


def no_token():
    raise FigmaAuthError(401, "set FIGMA_TOKEN")


@pytest.fixture
def ui(request):
    factory = getattr(request, "param", no_token)
    server = make_server(App(factory))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    with httpx.Client(base_url=base) as http:
        page = http.get("/").text
        key = page.split('name="figma-fit-key" content="')[1].split('"')[0]
        http.headers[KEY_HEADER] = key
        yield http
    server.shutdown()
    server.server_close()


def fit(http, **request):
    return http.post("/api/fit", json=request)


def test_page_is_served_with_a_fresh_key(ui):
    page = ui.get("/").text
    assert "__FIGMA_FIT_KEY__" not in page
    assert len(ui.headers[KEY_HEADER]) > 20


def test_sample_works_without_a_token(ui):
    assert ui.get("/api/status").json() == {"has_token": False}
    r = fit(ui, source="sample", budget=20000)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "fit"
    assert data["tokens"] <= 20000 < data["original_tokens"]
    assert data["report"].startswith("figma-fit: ")
    assert [n["pass"] for n in data["notes"]][:2] == ["drop_invisible", "flatten_wrappers"]
    assert data["body"]["file"]["name"].startswith("Sample:")
    assert data["text"].startswith(data["report"])


def test_sample_at_a_small_budget_is_a_split_plan(ui):
    data = fit(ui, source="sample", budget=3000).json()
    assert data["status"] == "split"
    assert data["body"]["calls"]


def test_saved_capture(ui, pricing_body):
    data = fit(ui, source="capture", name="pricing", capture=pricing_body, budget=5000).json()
    assert data["body"]["data"][0]["name"] == "Pricing"


def test_link_without_a_token_asks_for_one(ui):
    r = fit(ui, source="link", url=LINK, budget=5000)
    assert r.status_code == 400
    assert r.json()["code"] == "needs_token"


@respx.mock
def test_link_with_a_token_from_the_page_is_fetched_once(ui, pricing_body):
    respx.route(host="127.0.0.1").pass_through()
    route = respx.get(f"{API_BASE}/v1/files/FileKey/nodes").mock(
        return_value=httpx.Response(200, json=pricing_body)
    )
    first = fit(ui, source="link", url=LINK, budget=5000, token="from-page")
    assert first.status_code == 200, first.text
    assert route.calls.last.request.headers["X-Figma-Token"] == "from-page"
    assert ui.get("/api/status").json() == {"has_token": True}

    fit(ui, source="link", url=LINK, budget=5000)
    assert route.call_count == 1  # served from cache
    fit(ui, source="link", url=LINK, budget=5000, refresh=True)
    assert route.call_count == 2


@pytest.mark.parametrize("ui", [lambda: FigmaClient("from-env")], indirect=True)
def test_token_from_the_environment_is_used(ui):
    assert ui.get("/api/status").json() == {"has_token": True}


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        ({"source": "link", "url": "https://www.figma.com/design/abc/x", "token": "t"}, "node-id"),
        ({"source": "sample", "budget": 10}, "at least 1000"),
        ({"source": "sample", "budget": "big"}, "whole number"),
        ({"source": "capture", "capture": "nope"}, "not a saved Figma"),
        ({"source": "capture", "capture": {"nodes": {}}}, "no Figma nodes"),
        ({"source": "elsewhere"}, "unknown source"),
    ],
)
def test_bad_requests_get_a_readable_error(ui, request_, message):
    r = fit(ui, **request_)
    assert r.status_code == 400
    assert message in r.json()["error"]


def test_api_rejects_a_missing_or_wrong_key(ui):
    for key in ("", "wrong"):
        r = ui.post("/api/fit", json={"source": "sample"}, headers={KEY_HEADER: key})
        assert r.status_code == 403
    assert ui.get("/api/status", headers={KEY_HEADER: "wrong"}).status_code == 404


def test_requests_for_another_host_are_rejected(ui):
    # DNS rebinding: the browser sends the attacker's host name.
    assert ui.get("/", headers={"Host": "evil.example:80"}).status_code == 403
    r = ui.post("/api/fit", json={"source": "sample"}, headers={"Host": "evil.example"})
    assert r.status_code == 403


def test_non_object_body_is_rejected(ui):
    r = ui.post("/api/fit", content=json.dumps([1, 2]))
    assert r.status_code == 400
