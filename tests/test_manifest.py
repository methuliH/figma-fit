"""The Claude Desktop extension manifest stays in step with the code."""

import asyncio
import json
import tomllib
from pathlib import Path

from figma_fit.server import create_server

ROOT = Path(__file__).parent.parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def test_version_matches_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert MANIFEST["version"] == project["version"]


def test_listed_tools_are_the_servers_tools():
    async def names():
        return sorted(t.name for t in await create_server().list_tools())

    assert sorted(t["name"] for t in MANIFEST["tools"]) == asyncio.run(names())


def test_token_comes_from_a_sensitive_user_setting():
    env = MANIFEST["server"]["mcp_config"]["env"]
    assert env["FIGMA_TOKEN"] == "${user_config.figma_token}"
    setting = MANIFEST["user_config"]["figma_token"]
    assert setting["sensitive"] is True and setting["required"] is True


def test_server_runs_the_figma_fit_command_from_the_bundle():
    server = MANIFEST["server"]
    assert server["type"] == "uv"
    assert (ROOT / server["entry_point"]).is_file()
    args = server["mcp_config"]["args"]
    assert args[:3] == ["run", "--directory", "${__dirname}"]
    assert args[-1] == "figma-fit"


def test_bundle_keeps_what_uv_needs_to_build_the_project():
    lines = (ROOT / ".mcpbignore").read_text(encoding="utf-8").splitlines()
    ignored = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    for needed in ("README.md", "pyproject.toml", "uv.lock", "src/", "icon.png", "LICENSE"):
        assert needed not in ignored
    assert (ROOT / MANIFEST["icon"]).is_file()
