"""Check a built .mcpb starts the way Claude Desktop starts it.

    python scripts/check_extension.py dist/figma-fit.mcpb

Unpacks the bundle into a temporary folder, launches the server with the
manifest's own command (filling in ${__dirname} and a dummy token), then
checks over MCP that it initializes and lists exactly the manifest's tools.
Needs uv on PATH, as Claude Desktop does. Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(sys.argv[1]) as bundle:
            bundle.extractall(tmp)
        check(Path(tmp))
    print("extension OK")


def check(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["server"]["mcp_config"]

    def fill(value: str) -> str:
        value = value.replace("${__dirname}", str(root))
        for key in manifest.get("user_config", {}):
            value = value.replace(f"${{user_config.{key}}}", "dummy")
        return value

    env = {**os.environ, **{k: fill(v) for k, v in config.get("env", {}).items()}}
    env.pop("VIRTUAL_ENV", None)  # don't let an active venv stand in for the bundle's own
    proc = subprocess.Popen(
        [config["command"], *map(fill, config.get("args", []))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert proc.stdin and proc.stdout

    def call(msg_id: int, method: str, params: dict | None = None) -> dict:
        request = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            sys.exit(f"server exited before answering {method} (code {proc.wait()})")
        reply = json.loads(line)
        if "error" in reply:
            sys.exit(f"{method} failed: {reply['error']}")
        return reply["result"]

    try:
        info = call(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "check_extension", "version": "0"},
            },
        )["serverInfo"]
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.write("\n")
        proc.stdin.flush()
        tools = sorted(t["name"] for t in call(2, "tools/list")["tools"])
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)

    expected = sorted(t["name"] for t in manifest.get("tools", []))
    if info.get("version") != manifest["version"]:
        sys.exit(
            f"server reports version {info.get('version')}, manifest says {manifest['version']}"
        )
    if tools != expected:
        sys.exit(f"server tools {tools} != manifest tools {expected}")
    print(f"{info['name']} {info['version']}: {', '.join(tools)}")


if __name__ == "__main__":
    main()
