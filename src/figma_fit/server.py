"""MCP server: two tools, kept small because tool definitions cost tokens too."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from figma_fit import __version__
from figma_fit.figma import FigmaAPIError, FigmaClient, FigmaRateLimitError
from figma_fit.fit import MIN_BUDGET, BudgetError, fit_nodes
from figma_fit.passes import PASS_NAMES, select_passes
from figma_fit.url import FigmaURLError, normalize_node_id, parse_figma_url

DEFAULT_BUDGET = 20_000

Budget = Annotated[int, Field(ge=MIN_BUDGET, description="Max tokens for the response.")]
Passes = Annotated[
    list[str] | None,
    Field(description=f"Subset of {list(PASS_NAMES)} to allow. Default: all."),
]
PlanOffset = Annotated[int, Field(ge=0, description="Skip this many calls of a split plan.")]


def create_server(client_factory: Callable[[], FigmaClient] = FigmaClient.from_env) -> MCPServer:
    server = MCPServer(
        "figma-fit",
        version=__version__,
        instructions=(
            "Fetch Figma frames as compact JSON that never exceeds the token budget. "
            "The first line of each result reports size and what was removed."
        ),
    )
    client: FigmaClient | None = None

    def get_client() -> FigmaClient:
        nonlocal client
        if client is None:
            client = _call(client_factory)
        return client

    @server.tool()
    def fetch_within_budget(
        url: Annotated[str, Field(description="Figma frame link (with node-id).")],
        budget: Budget = DEFAULT_BUDGET,
        passes: Passes = None,
        plan_offset: PlanOffset = 0,
    ) -> str:
        """Fetch a Figma frame compacted to fit `budget` tokens, or a plan of smaller calls."""
        # Validate everything before fetching: some plans allow only a few requests a month.
        ref = _call(parse_figma_url, url)
        selected = _call(select_passes, passes)
        fetched = _call(get_client().fetch_nodes, ref.file_key, [ref.node_id])
        return _call(_fit, fetched, budget, selected, plan_offset)

    @server.tool()
    def fetch_node_within_budget(
        file_key: str,
        node_ids: Annotated[list[str], Field(min_length=1, description="From a split plan.")],
        budget: Budget = DEFAULT_BUDGET,
        passes: Passes = None,
        plan_offset: PlanOffset = 0,
    ) -> str:
        """Fetch nodes listed in a split plan (served from cache), compacted to fit `budget`."""
        ids = [_call(normalize_node_id, n) for n in node_ids]
        selected = _call(select_passes, passes)
        fetched = _call(get_client().fetch_nodes, file_key, ids)
        return _call(_fit, fetched, budget, selected, plan_offset)

    return server


def _fit(fetched, budget: int, passes, plan_offset: int) -> str:
    return fit_nodes(fetched, budget, passes=passes, plan_offset=plan_offset).text


def _call(fn, *args):
    """Run fn, turning anticipated failures into messages the model can act on."""
    try:
        return fn(*args)
    except FigmaRateLimitError as e:
        wait = f" Retry after {e.retry_after}s." if e.retry_after is not None else ""
        raise ToolError(
            f"Figma rate limit hit.{wait} Do not retry in a loop: limits on some plans are "
            "monthly. Use node ids from an earlier split plan; those are served from cache."
        ) from e
    except (FigmaAPIError, FigmaURLError, BudgetError, ValueError) as e:
        raise ToolError(str(e)) from e


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
