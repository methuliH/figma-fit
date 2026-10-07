# figma-fit

An MCP server that fetches Figma design data **guaranteed to fit a token budget**, and tells you what it removed to get there. When a frame can't fit, it returns a plan of smaller calls that each do.

```
figma-fit: 7.7k/20.0k tokens (est.) · saved 77% from 33.1k · drop_invisible −30 nodes (6 hidden, 6 clipped off-canvas) · flatten_wrappers −6 wrappers · dedupe_styles 193 paints→5 · collapse_instances Row×55 (−108 nodes)
{"status":"fit","file":{...},"legend":{...},"data":[...]}
```

Why: Figma responses routinely blow past agent context limits (Figma's own known-issues page quotes a 351k-token `get_design_context` against a 25k cap). See [PLAN.md](PLAN.md) for the full analysis of existing tools.

## What it does

- **Hard budget.** Every response is estimated at or under `budget`. If compaction can't reach it, you get a split plan, never an oversized payload.
- **Itemized report.** The first line of every response says what each pass removed and how many tokens it saved.
- **Sized split plan.** Each suggested follow-up call lists its node ids and estimated size. Follow-ups are served from cache, so they cost no extra Figma requests.
- **Headless.** Uses the Figma REST API with a personal access token. No Figma Desktop needed, so it works in CI, cloud agents and remote sessions.

## Setup

1. Create a Figma personal access token with the `file_content:read` scope (Figma → Settings → Security → Personal access tokens).
2. Add the server to Claude Code:

```bash
claude mcp add figma-fit --env FIGMA_TOKEN=<your-token> -- uvx --from git+https://github.com/<you>/figma-fit figma-fit
```

From a local checkout instead:

```bash
claude mcp add figma-fit --env FIGMA_TOKEN=<your-token> -- uv run --directory "/path/to/figma-fit" figma-fit
```

Then ask for a frame: in Figma, right-click a frame → **Copy link to selection**, and paste the link. A link without `node-id` is refused, because whole files are the case that blows every budget.

## Tools

| Tool | Arguments | Use |
|---|---|---|
| `fetch_within_budget` | `url`, `budget` = 20000, `passes`, `plan_offset` | Main tool. Fit a frame, or get a split plan. |
| `fetch_node_within_budget` | `file_key`, `node_ids`, `budget`, `passes`, `plan_offset` | Follow-up calls from a split plan (served from cache). |

`budget` must be at least 1000. `plan_offset` pages through a split plan that is too long to list in one response.

## How it shrinks data

Passes run in order and **stop as soon as the output fits**, so a frame that already fits comes back with full detail.

| Pass | What it does | Loss |
|---|---|---|
| `drop_invisible` | Removes hidden and zero-opacity layers, layers fully outside a clipping frame (or the requested frame), and hidden paints/effects | None for rendering |
| `flatten_wrappers` | Replaces single-child frames/groups that paint, clip and lay out nothing with their child | None for rendering |
| `dedupe_styles` | Moves paints, effects and text styles used 2+ times into `legend.styles`; nodes refer to them as `"@p1"` | None |
| `collapse_instances` | Repeated instances of a component (same variant and size) become `sameAs` + a JSON-pointer `diff` against the first one | None (the diff rebuilds the node) |
| `minify` | Drops default values, writes colours as hex and boxes as `[x, y, w, h]`, shortens long keys (listed in `legend.keys`), rounds floats to 2 decimals | Rounding (reported) |

Restrict them with `passes`, e.g. `["drop_invisible", "minify"]`.

## How the guarantee works

- Tokens are estimated as UTF-8 bytes / 3.2 on the **exact string returned**, report line included. Dense JSON tokenizes worse than prose, so this is deliberately more pessimistic than the usual chars / 4.
- Output is held to 80% of the budget (`SAFETY = 0.8`), so an estimate that runs up to 20% low still fits.
- A property test (`tests/test_fit.py`) checks the claim on synthetic frames from a few thousand to a few hundred thousand tokens with random budgets, and checks that every planned follow-up call also fits.

The estimate is not yet calibrated against real Claude token counts. Until it is, treat the guarantee as "by estimate". To calibrate:

```bash
uv run --group calibrate python scripts/calibrate.py
```

This counts real tokens with Anthropic's token-counting endpoint on your recorded captures, and reports whether the estimate stays safe.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
```

Record a real frame as a fixture (writes to the git-ignored `captures/`; scrub private names and text before moving it into `tests/fixtures/`):

```bash
FIGMA_TOKEN=... uv run python scripts/record_fixture.py "<figma frame url>"
```

## Limits (v1)

- Design files only. FigJam and Slides links are refused, because the passes are written for design-file layers.
- Split plans send a section's children as separate calls. The parent's own layout fields (auto-layout direction, gap, padding) are not repeated in each follow-up.
- Estimates are byte-based, not exact counts. Exact counting is on the v2 list in [PLAN.md](PLAN.md#28-v2-backlog-in-priority-order).
