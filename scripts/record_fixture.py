"""Record a raw Figma REST response for a frame URL, for use as a test fixture.

    FIGMA_TOKEN=... uv run python scripts/record_fixture.py <figma-url> [name]

Writes to captures/<name>.json (git-ignored). Scrub private names and text
before moving a capture into tests/fixtures/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

from figma_fit.figma import API_BASE, TOKEN_ENV_VARS
from figma_fit.tokens import estimate
from figma_fit.url import parse_figma_url


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ref = parse_figma_url(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else f"{ref.file_key}_{ref.node_id.replace(':', '-')}"

    token = next((os.environ[v] for v in TOKEN_ENV_VARS if os.environ.get(v)), None)
    if not token:
        sys.exit(f"set {' or '.join(TOKEN_ENV_VARS)}")

    response = httpx.get(
        f"{API_BASE}/v1/files/{ref.file_key}/nodes",
        params={"ids": ref.node_id},
        headers={"X-Figma-Token": token},
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()

    out = Path("captures") / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(body, indent=1, ensure_ascii=False))
    print(f"wrote {out} ({len(response.content):,} bytes, ~{estimate(body):,} tokens est.)")


if __name__ == "__main__":
    main()
