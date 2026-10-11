"""Command line entry point.

figma-fit                 run the MCP server over stdio (what MCP clients launch)
figma-fit fetch <link>    print what Claude would receive for one frame
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from figma_fit.figma import FetchedNode, FigmaAPIError, FigmaClient, nodes_from_body
from figma_fit.fit import BudgetError, fit_nodes
from figma_fit.samples import load_sample
from figma_fit.server import DEFAULT_BUDGET
from figma_fit.url import FigmaURLError, parse_figma_url


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="figma-fit",
        description="Figma design data that always fits your token budget.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.add_parser("serve", help="run the MCP server over stdio (the default)")

    fetch = sub.add_parser("fetch", help="fetch one frame and print what Claude would receive")
    fetch.add_argument("url", nargs="?", help="Figma frame link (Copy link to selection)")
    fetch.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="max tokens")
    source = fetch.add_mutually_exclusive_group()
    source.add_argument(
        "--capture", type=Path, help="use a saved Figma API response instead of calling Figma"
    )
    source.add_argument(
        "--sample", action="store_true", help="use the built-in sample design (no token needed)"
    )
    fetch.add_argument("--report", action="store_true", help="print only the size report line")

    args = parser.parse_args(argv)
    if args.command in (None, "serve"):
        from figma_fit.server import main as serve

        serve()
        return
    if args.url is None and args.capture is None and not args.sample:
        parser.error("fetch needs a Figma link, a --capture file, or --sample")
    sys.exit(_fetch(args))


def _fetch(args: argparse.Namespace) -> int:
    # Windows consoles default to a legacy code page; the report uses "·", "×", "→".
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        nodes = load_sample() if args.sample else _load(args.url, args.capture)
        text = fit_nodes(nodes, args.budget).text
    except (FigmaAPIError, FigmaURLError, BudgetError, ValueError, OSError) as e:
        print(f"figma-fit: {e}", file=sys.stderr)
        return 1
    print(text.split("\n", 1)[0] if args.report else text)
    return 0


def _load(url: str | None, capture: Path | None) -> list[FetchedNode]:
    ref = parse_figma_url(url) if url else None
    if capture is not None:
        body = json.loads(capture.read_text(encoding="utf-8"))
        file_key = ref.file_key if ref else capture.stem
        return nodes_from_body(file_key, body, [ref.node_id] if ref else None)
    assert ref is not None
    with FigmaClient.from_env() as client:
        return client.fetch_nodes(ref.file_key, [ref.node_id])


if __name__ == "__main__":
    main()
