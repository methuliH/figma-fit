import json

import httpx
import pytest
import respx

from figma_fit import cli
from figma_fit.figma import API_BASE

FIXTURE = "tests/fixtures/pricing_nodes.json"
URL = "https://www.figma.com/design/FileKey/Shop?node-id=12-1"


def run(capsys, *argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(list(argv))
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


def test_fetch_from_capture_prints_report_and_data(capsys):
    code, out, _ = run(capsys, "fetch", "--capture", FIXTURE)
    assert code == 0
    line, body = out.split("\n", 1)
    assert line.startswith("figma-fit: ")
    assert json.loads(body)["data"][0]["name"] == "Pricing"


def test_fetch_report_only(capsys):
    code, out, _ = run(capsys, "fetch", "--capture", FIXTURE, "--report", "--budget", "1000")
    assert code == 0
    assert out.count("\n") == 1 and out.startswith("figma-fit: ")


def test_capture_with_link_picks_that_node(capsys):
    code, out, _ = run(capsys, "fetch", URL, "--capture", FIXTURE)
    assert code == 0
    assert json.loads(out.split("\n", 1)[1])["file"]["key"] == "FileKey"


@respx.mock
def test_fetch_live_uses_the_token(capsys, monkeypatch, pricing_body):
    monkeypatch.setenv("FIGMA_TOKEN", "secret")
    route = respx.get(f"{API_BASE}/v1/files/FileKey/nodes").mock(
        return_value=httpx.Response(200, json=pricing_body)
    )
    code, out, _ = run(capsys, "fetch", URL, "--report")
    assert code == 0 and out.startswith("figma-fit: ")
    assert route.calls.last.request.headers["X-Figma-Token"] == "secret"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["fetch", "https://www.figma.com/design/abc/x"], "node-id"),
        (["fetch", "--capture", "missing.json"], "No such file"),
        (["fetch", "--capture", FIXTURE, "--budget", "10"], "at least 1000"),
    ],
)
def test_errors_go_to_stderr_with_exit_code_1(capsys, argv, message):
    code, out, err = run(capsys, *argv)
    assert code == 1 and out == ""
    assert message in err


def test_fetch_without_link_or_capture_is_a_usage_error(capsys):
    code, _, err = run(capsys, "fetch")
    assert code == 2
    assert "needs a Figma link" in err


@pytest.mark.parametrize("argv", [[], ["serve"]])
def test_no_command_runs_the_mcp_server(monkeypatch, argv):
    calls = []
    monkeypatch.setattr("figma_fit.server.main", lambda: calls.append(True))
    cli.main(argv)
    assert calls == [True]
