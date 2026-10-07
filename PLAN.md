# figma-fit: Analysis and Build Plan

**Goal:** one MCP tool, `fetch_within_budget(url, budget)`. It returns Figma design data that is guaranteed to fit a token budget, plus a report of what it changed. When the data cannot fit, it returns a split plan instead.

This document has two parts:

1. **Analysis.** What already exists, what has changed since plan v2 was written, and where the gap really is.
2. **Build plan.** Architecture, algorithms, milestones with acceptance criteria, testing and calibration.

Research date: 2026-10-07. Re-check anything marked *verify* before you rely on it.

---

## Part 1. Analysis of existing solutions

### 1.1 The problem is real and still happening

- **Claude Code:** `get_design_context response (351378 tokens) exceeds maximum allowed tokens (25000)`. This is quoted in Figma's own known-issues page.
- **Figma forum:** a user found the API payload was about 960k tokens while the Figma UI estimated about 67k for the same component. They asked for a way to see the real size before making the request. As far as I can find, there is still no such API.
- **Cursor and Notion threads:** responses blow past context limits in the same way. So the problem is not specific to Figma.

### 1.2 Landscape

| Tool | Data source | How it shrinks output | Budget parameter? | Guarantee? | Drop report? | Split guidance? |
|---|---|---|---|---|---|---|
| **Official Figma MCP** (`get_design_context`, `get_metadata`) | Figma (Desktop or remote) | Generates code or a reference, not raw JSON | No | No | No | **Partial.** When a design is too large, it returns a *sparse metadata response* and tells the agent to call `get_design_context` on sublayer IDs. There are no size estimates per sublayer. |
| **Claude Code `MAX_MCP_OUTPUT_TOKENS`** | n/a | Raises the cap instead of shrinking the response | n/a | n/a | n/a | n/a |
| **figma-compaction-mcp** (s9hn, TS, v3.0.2, about 2 stars) | Proxies the **local Figma Desktop MCP** (`127.0.0.1:3845`) | Line-based DSL; modes `minimal`/`balanced`/`debug`; task hints | **Yes: `max_output_chars`** | No. Its README says large screens "can still return larger output" | Optional `include_stats` (size stats, not a list of what was dropped) | No |
| **Framelink / figma-developer-mcp** (GLips, TS, 16k+ stars) | REST API | Simplified YAML/JSON of layout and styles | No (has a `depth` parameter) | No | No | Manual, through `depth` |
| **figma-mcp-chunked** (ArchimedesCrypto) | REST API | Chunking and pagination by node count | Chunk size (nodes, not tokens) | No | No | Pagination, not a plan |
| **@alucardeht/figma-mcp** | REST API | Frame info and chunked access | No (*verify*) | No | No | Partial (*verify*) |
| **felixAnhalt figma-to-code-mcp** | REST API | Fixed pruning | No (*verify*) | No | No | No |
| **Generic token-cost tools** (PolicyLayer, web calculators) | n/a | Measure *tool definitions*, not responses | n/a | n/a | n/a | n/a |

### 1.3 What changed since plan v2

Two facts weaken the claim "Budget-guaranteed fetch: nothing found". Neither one removes the gap.

1. **figma-compaction-mcp now accepts `max_output_chars`.** So "has a budget knob" no longer sets this project apart. What it still lacks is a *guarantee*: its own docs say the output can exceed the budget. It also only works when the Figma Desktop app is running, because it proxies the local Desktop MCP.
2. **Figma's official server already falls back to a sparse node map** when a design is too large. That is a rough version of a "split plan". It has no per-node size estimates, though, and nothing tells the agent that each suggested call will fit.

### 1.4 Where the gap actually is

The defensible pitch is narrower than "nobody does budgets". It has five parts, and **no existing tool does all five**:

1. **Hard guarantee.** The response is never larger than `budget`. If compaction cannot reach it, the tool returns a split plan, never an oversized payload.
2. **Itemized drop report.** It lists what was removed, per pass, with counts and tokens saved. This lets the agent know what it *isn't* seeing.
3. **Sized split plan.** Each suggested follow-up node comes with an estimated size that fits the budget. Figma's sparse fallback gives IDs only.
4. **Works headless.** It uses the REST API with a personal access token, so it runs without Figma Desktop. That matters for CI, cloud agents and remote sessions. figma-compaction-mcp needs Desktop.
5. **Generic pipeline.** The passes work on JSON trees, so the same engine can later wrap Notion or any other MCP that returns trees.

### 1.5 Competitive risks

| Risk | Likelihood | Response |
|---|---|---|
| Figma adds sizes to its sparse fallback, or adds a budget parameter | Medium | Keep v1 to about a weekend. Headless REST and the generic pipeline still set it apart. |
| figma-compaction-mcp makes `max_output_chars` a hard guarantee | Low to medium | Step zero below: if they come close, contribute a PR to them instead. |
| Users just raise `MAX_MCP_OUTPUT_TOKENS` | High for people with a large context | The pitch is "fits *and* tells you what it dropped", not only "fits". Big responses still waste context and cost. |
| The REST tree is a worse basis for code generation than `get_design_context` | Medium | Check in milestone M4 (build from the output and compare). Proxy mode for the official MCP stays in v2. |

### 1.6 Verdict

**Build it**, but run step zero first. Step zero is now sharper: test whether figma-compaction-mcp with `max_output_chars` **actually stays within budget** on your biggest frames, and test what Figma's sparse fallback looks like on the same frames.

---

## Part 2. Build plan

### 2.0 Step zero: validate (about 1 hour)

1. Pick 3 frames: small (under 10k tokens), medium (about 50k) and huge (over 200k).
2. For each frame, record:
   - The size of the official `get_design_context` output, and whether you got the sparse fallback.
   - The figma-compaction-mcp output size with `max_output_chars` = 100k (about a 25k-token budget).
   - The Framelink output size with no depth limit and with `depth=2`.
3. Decide:

| Result | Decision |
|---|---|
| figma-compaction-mcp is within budget on all 3 frames | Open a PR adding a drop report and split plan to it. Stop here. |
| It goes over budget on the huge frame, or needs Desktop and you want headless | **Build figma-fit.** |
| You want the generic any-MCP engine anyway | **Build figma-fit.** |

Save every raw response from this step as a test fixture (see 2.7). They are your calibration set.

### 2.1 Architecture

```
            MCP client (Claude Code, Cursor, ...)
                         │  fetch_within_budget(url, budget)
                         ▼
┌──────────────────────── figma-fit server ────────────────────────┐
│ url.py      parse URL → (file_key, node_id)                      │
│ figma.py    REST fetch + per-session cache (keyed by version)    │
│ tokens.py   estimate(obj) → int   (pluggable estimator)          │
│ passes/     pure fns: tree → (tree, PassNote)   ← Figma rules    │
│ pipeline.py run passes in order until estimate ≤ effective budget│
│ split.py    greedy grouping of children into budget-sized calls  │
│ report.py   one-line + structured size report                    │
│ server.py   MCP tool definitions (FastMCP)                       │
└──────────────────────────────────────────────────────────────────┘
```

**Rule:** `pipeline.py`, `split.py`, `tokens.py` and `report.py` know nothing about Figma. Only `passes/figma_*.py`, `url.py` and `figma.py` do. That keeps the Notion version in v2 to a new set of passes plus a new fetcher.

### 2.2 Repository layout

```
figma-fit/
├── pyproject.toml            # uv; entry point `figma-fit` → runnable via `uvx figma-fit`
├── README.md
├── PLAN.md
├── src/figma_fit/
│   ├── __init__.py
│   ├── server.py             # FastMCP app, tool registration
│   ├── url.py
│   ├── figma.py              # httpx client, retries on 429, cache
│   ├── tokens.py
│   ├── pipeline.py
│   ├── split.py
│   ├── report.py
│   ├── models.py             # PassNote, SizeReport, SplitPlan, FitResult
│   └── passes/
│       ├── __init__.py       # DEFAULT_PASSES ordered list
│       ├── base.py           # Pass protocol
│       ├── figma_invisible.py
│       ├── figma_flatten.py
│       ├── figma_styles.py
│       ├── figma_instances.py
│       └── generic_minify.py # key shortening, rounding, defaults, compact serialization
└── tests/
    ├── fixtures/             # recorded REST responses (scrubbed)
    ├── test_url.py
    ├── test_passes_*.py
    ├── test_pipeline.py
    ├── test_split.py
    └── test_server.py
```

### 2.3 Core contracts

```python
# models.py
@dataclass
class PassNote:
    pass_name: str          # "drop_invisible"
    removed: str            # "41 hidden nodes, 3 zero-opacity nodes"
    tokens_before: int
    tokens_after: int

@dataclass
class SplitItem:
    node_id: str            # "12:4"
    name: str               # "Header"
    est_tokens: int         # after compaction

@dataclass
class FitResult:
    status: Literal["fit", "split"]
    data: dict | None       # compacted tree (status == "fit")
    legend: dict | None     # style tokens, key map (if shortened)
    split_plan: list[list[SplitItem]] | None   # groups; each group = one follow-up call
    report: SizeReport

# passes/base.py
class Pass(Protocol):
    name: str
    def __call__(self, tree: dict, ctx: PassContext) -> tuple[dict, str]: ...
    # Pure: returns a NEW tree plus a human note. No I/O.
```

**MCP tool surface (v1):**

| Tool | Args | Purpose |
|---|---|---|
| `fetch_within_budget` | `url: str`, `budget: int = 20000`, `passes: list[str] \| None` | Main tool. |
| `fetch_node_within_budget` | `file_key: str`, `node_id: str`, `budget: int` | Follow-up for split-plan items. Uses the cache, so it costs no new API call. |

Keep the tool count at 2. Tool-definition cost is part of the pitch.

### 2.4 Algorithms

**URL parsing (`url.py`)**

- Handle `figma.com/design/:key/...`, `/file/:key/...` (legacy), and `/design/:key/branch/:branchKey/...`. For a branch URL, use the branch key.
- Read `node-id` from the query string and convert `1-2` to `1:2`. Also accept URL-encoded `1%3A2`.
- Reject `/board/` (FigJam) and `/slides/` with a clear message in v1.
- If there is no `node-id`, refuse. A whole-file fetch is the 960k-token case. Ask for a frame link instead.

**Fetch (`figma.py`)**

- Call `GET /v1/files/{key}/nodes?ids={id}` with header `X-Figma-Token`. Do not request geometry (leave out `geometry=paths`). Vector paths are huge and useless for code generation.
- **Caching moves into v1** (it was in v2). This is a new reason: Figma rate limits depend on plan and seat. For example, a personal access token reading a Starter-plan file can be limited to **6 requests per month**. A split plan that triggers 4 more REST calls would use up that quota. So: fetch the subtree once, cache it by `(file_key, node_id, file version)` for the session, and serve split-plan follow-ups from that cached subtree.
- On 429, read `Retry-After` and return a clear error. Do not loop.

**Token estimate (`tokens.py`)**

- v1 default: `len(serialized) / 3.2`, not `/4`. Dense JSON with IDs, hex values and punctuation tokenizes worse than prose. Calibrate this number in M4.
- Measure the *exact string the tool will return*, after serialization. Never measure the Python dict.
- Keep it pluggable (`Estimator` protocol) so v2 can plug in exact counting through Anthropic's token-counting endpoint (*verify the current API*).

**Pipeline (`pipeline.py`)**

```
effective = floor(budget * SAFETY)        # SAFETY = 0.80 until calibrated
                - report_overhead - legend_overhead
tree = fetched
for p in passes:                          # cheapest and most information-preserving first
    if estimate(tree) <= effective: break
    tree, note = p(tree)
    notes.append(note)
if estimate(serialize(tree)) <= effective: return FIT
else: return SPLIT(build_split_plan(original_tree))
```

- Run passes **in order and stop early**. Do not run the destructive passes when the cheap ones are enough. That keeps the most information.
- *Always* apply compact serialization (no whitespace, `separators=(",",":")`). It changes no information and often saves 20 to 30%.

**Passes (in order)**

| # | Pass | Rule (Figma REST fields) | Strictly lossless? |
|---|---|---|---|
| 1 | `drop_invisible` | Remove nodes with `visible: false`, `opacity == 0`, or an `absoluteBoundingBox` fully outside the root frame's box | Yes for rendering |
| 2 | `flatten_wrappers` | A FRAME/GROUP with exactly 1 child, no `fills`/`strokes`/`effects`, no auto-layout padding or spacing, and no `clipsContent` gets replaced by its child (keep the child's name and bounds) | Yes for rendering |
| 3 | `dedupe_styles` | Hash each `fills`/`strokes`/`effects`/`style` object. Values used 2+ times move to `legend.styles` as `c1`, `t1` and so on, and the node refers to the key | Yes |
| 4 | `collapse_instances` | Group INSTANCE siblings by `componentId` + `componentProperties` + size. Emit `{"instance":"Card","count":12,"props":{...}}` plus the instances that differ | Yes (the diffs are kept) |
| 5 | `minify` | Drop default values (`blendMode: PASS_THROUGH`, `opacity: 1`, empty arrays, `visible: true`); round floats to 1 decimal place; shorten keys using a legend | **Rounding is slightly lossy.** Report it as such |

Call these **"render-preserving"** passes, not "lossless". Rounding and dropping off-canvas nodes do change the data. Being honest about that is part of what the drop report is for.

**Split plan (`split.py`)**

```
def plan(node, budget):
    size = estimate(compact(node))
    if size <= budget: return [[item(node, size)]]
    if not node.children: return [[item(node, size, oversize=True)]]   # leaf too big: report it, never send it
    groups = []
    for child in node.children:
        groups += plan(child, budget)            # recurse into oversized children
    return greedy_pack(groups, budget)           # first-fit decreasing: bundle small siblings into one call
```

- **Every group is guaranteed to be ≤ budget** by construction. A leaf that is too big on its own (for example a huge text block or a vector) is marked `oversize` with a suggested next step. It is never returned as data.
- The split response itself must also fit the budget. If the plan is extremely long, cut it to the top N groups and add "+K more" with a cursor.

**Size report (`report.py`)**

One line goes at the top of every response, and the same data is also included as structured JSON:

```
figma-fit: 18.2k/25k tokens (est.) · saved 61% from 46.9k · drop_invisible −41 nodes · dedupe_styles 23→7 colors · collapse_instances Card×12
```

### 2.5 Milestones (weekend schedule plus a calibration day)

| Block | Deliverable | Acceptance criteria |
|---|---|---|
| **M0** (Fri eve, 1h) | Step zero + `uv init` + repo skeleton + PAT in `.env` | Comparison table filled in; decision recorded at the end of this file |
| **M1** (Sat AM) | `url.py`, `figma.py` (with cache), `tokens.py` | Unit tests for 8+ URL shapes; one real fetch saved as a fixture; the second fetch of the same node makes 0 HTTP calls |
| **M2** (Sat PM) | `pipeline.py` + 5 passes | Each pass has a fixture test (input → expected output + note); running the passes again changes nothing; each pass shrinks the medium fixture or no-ops cleanly |
| **M3** (Sun AM) | Budget loop, `split.py`, `report.py` | Property test: for random budgets of 2k–50k on every fixture, the output is **never** over budget; on the huge fixture, every split group is ≤ budget |
| **M4** (Sun PM) | `server.py` (FastMCP), README, Claude Code config snippet | Works with `claude mcp add figma-fit -- uvx figma-fit`; build one real component in Claude from compacted output vs raw output and write down the quality difference |
| **M5** (+1 day) | Calibration | Compare 10–20 estimates against actual counts; set the divisor and `SAFETY` so that at least 95% of estimates are ≥ the actual count; record the error in the README |

### 2.6 Testing strategy

- **Recorded fixtures.** Store real REST responses in `tests/fixtures/`, scrubbed of names and text if the file is private. There are no live API calls in CI.
- **Pass tests.** Golden in/out JSON per pass.
- **Guarantee test.** A property-based test (`hypothesis`): for any fixture and any budget, `estimate(output) <= budget`. This is the most important test. It *is* the product claim.
- **Server test.** Call the tool through the MCP SDK in-memory client and check the response shape.
- **Quality check (manual, in M4).** Implement one component from compacted output vs raw output and record any visual or structural difference.

### 2.7 Calibration (risk: estimate accuracy)

1. For each fixture, store the compacted output string.
2. Get the real token count from Anthropic's token-counting endpoint (*verify the current API and its pricing*) or from the client's own reported count.
3. Fit `actual ≈ chars / k` and choose `k` and `SAFETY` so that the estimate overshoots at least 95% of the time.
4. Publish the measured error in the README. "Within X% on N real frames" is a strong portfolio line.

### 2.8 v2 backlog (in priority order)

1. **Exact counting** through the token-counting API (cache counts per output hash).
2. **Lossy passes, each reported:** summarize beyond depth N, drop `effects`/`exportSettings`/plugin data, truncate long text with "…(+340 chars)".
3. **Proxy mode** for the official Figma MCP (`get_design_context`), so the guarantee also covers Figma's own output. It is also the stronger answer to "REST output differs from MCP output".
4. **Notion adapter.** A new fetcher plus block-tree passes; the pipeline stays the same.
5. Persistent cache keyed by file `version`.

### 2.9 Risks and mitigations

| Risk | Mitigation |
|---|---|
| Estimates come in under the actual count, which breaks the guarantee | Conservative divisor + 0.8 safety margin + a property test; calibrate in M5 |
| REST rate limits (seat- and plan-dependent; Starter can be about 6/month) | Fetch once, cache the subtree, serve follow-ups from the cache; refuse whole-file fetches; show `Retry-After` |
| The REST tree is worse for code generation than `get_design_context` | Quality check in M4; proxy mode in v2 |
| Figma adds sizing or budgets to its own MCP | Keep v1 small; headless and generic-engine still set it apart |
| Private design data ends up in fixtures | Scrub script for fixtures; `.gitignore` the raw captures |

### 2.10 Stack

- Python 3.11+, `uv`, published so `uvx figma-fit` runs it
- `mcp` (official Python SDK, FastMCP)
- `httpx` (sync is fine for v1)
- `pytest`, `hypothesis`, `respx` (to mock httpx)
- `ruff` for lint and formatting

---

## Sources

- Figma MCP known issues (351k-token error, sparse metadata fallback, `get_metadata` workaround): https://developers.figma.com/docs/figma-mcp-server/mcp-clients-issues
- Figma forum, request for a token estimate through the API: https://forum.figma.com/ask-the-community-7/request-expose-the-optimized-estimated-tokens-schema-via-api-48396
- Figma REST API rate limits (seat, plan and tier based; Starter 6/month example): https://developers.figma.com/docs/rest-api/rate-limits
- figma-compaction-mcp (`max_output_chars`, modes, Desktop upstream): https://github.com/s9hn/figma-compaction-mcp and https://glama.ai/mcp/servers/s9hn/figma-compaction-mcp
- Framelink / figma-developer-mcp (`depth` parameter): https://github.com/GLips/Figma-Context-MCP
- figma-mcp-chunked: https://ubos.tech/mcp/figma-mcp-server-with-chunking/
- @alucardeht/figma-mcp: https://glama.ai/mcp/servers/@alucardeht/figma-mcp
- Kilo issue: https://github.com/Kilo-Org/kilocode/issues/2378
- Cursor forum (Figma and Notion large responses): https://forum.cursor.com/t/troubleshooting-large-response-errors-when-linking-mcps-with-cursor-in-figma-or-notion/58340
- PolicyLayer Figma token cost: https://policylayer.com/token-cost/ai-zerolab-mcp-figma
