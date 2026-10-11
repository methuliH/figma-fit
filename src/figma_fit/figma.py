"""Figma REST client with a per-session subtree cache.

Rate limits on some plans are tiny (a Starter-plan file can allow ~6 file
requests a month), so each subtree is fetched once and any node inside it,
including split-plan follow-ups, is served from the cache.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

import httpx

from figma_fit.url import FigmaRef

API_BASE = "https://api.figma.com"
TOKEN_ENV_VARS = ("FIGMA_TOKEN", "FIGMA_API_KEY")


class FigmaAPIError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Figma API error {status}: {message}")
        self.status = status
        self.message = message


class FigmaAuthError(FigmaAPIError):
    """Missing, invalid, or under-scoped token."""


class FigmaNotFoundError(FigmaAPIError):
    """File or node does not exist, or the token cannot see it."""


class FigmaRateLimitError(FigmaAPIError):
    def __init__(self, message: str, retry_after: int | None) -> None:
        super().__init__(429, message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class FetchedNode:
    file_key: str
    node_id: str
    file_name: str
    version: str
    last_modified: str
    document: dict[str, Any]
    components: dict[str, Any]
    component_sets: dict[str, Any]
    styles: dict[str, Any]
    from_cache: bool = False


class SubtreeCache:
    """Fetched subtrees, indexed so any descendant node can be looked up."""

    def __init__(self) -> None:
        self._entries: dict[str, list[tuple[FetchedNode, dict[str, dict[str, Any]]]]] = {}

    def put(self, fetched: FetchedNode) -> None:
        """Add a subtree. A new file version evicts everything cached from older ones,
        so a follow-up never mixes two versions of the design."""
        entries = [
            e for e in self._entries.get(fetched.file_key, []) if e[0].version == fetched.version
        ]
        index = {node["id"]: node for node in _walk(fetched.document) if "id" in node}
        entries.append((fetched, index))
        self._entries[fetched.file_key] = entries

    def get(self, file_key: str, node_id: str) -> FetchedNode | None:
        for fetched, index in reversed(self._entries.get(file_key, [])):
            node = index.get(node_id)
            if node is not None:
                return replace(fetched, node_id=node_id, document=node, from_cache=True)
        return None

    def clear(self) -> None:
        self._entries.clear()


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.get("children") or ())


class FigmaClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_BASE,
        timeout: float = 30.0,
        http: httpx.Client | None = None,
        cache: SubtreeCache | None = None,
    ) -> None:
        if not token:
            raise FigmaAuthError(401, "no Figma token provided")
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout)
        self._headers = {"X-Figma-Token": token}
        self.cache = cache if cache is not None else SubtreeCache()

    @classmethod
    def from_env(cls, **kwargs: Any) -> FigmaClient:
        for name in TOKEN_ENV_VARS:
            token = os.environ.get(name)
            if token:
                return cls(token, **kwargs)
        raise FigmaAuthError(
            401,
            f"set {' or '.join(TOKEN_ENV_VARS)} to a Figma personal access token "
            "with the file_content:read scope",
        )

    def fetch_node(self, ref: FigmaRef, *, refresh: bool = False) -> FetchedNode:
        """Fetch a node subtree, from the cache when it has been seen already."""
        return self.fetch_nodes(ref.file_key, [ref.node_id], refresh=refresh)[0]

    def fetch_nodes(
        self, file_key: str, node_ids: list[str], *, refresh: bool = False
    ) -> list[FetchedNode]:
        """Fetch several node subtrees of one file, in the order given.

        Nodes already cached (directly or inside a cached ancestor) cost no
        request; the rest are fetched together in one request. Vector geometry
        is not requested: it is large and useless for code.
        """
        found: dict[str, FetchedNode] = {}
        if not refresh:
            for node_id in node_ids:
                cached = self.cache.get(file_key, node_id)
                if cached is not None:
                    found[node_id] = cached

        missing = [n for n in dict.fromkeys(node_ids) if n not in found]
        if missing:
            response = self._http.get(
                f"/v1/files/{file_key}/nodes",
                params={"ids": ",".join(missing)},
                headers=self._headers,
            )
            _raise_for_status(response)
            for fetched in nodes_from_body(file_key, response.json(), missing):
                self.cache.put(fetched)
                found[fetched.node_id] = fetched

        return [found[n] for n in node_ids]

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FigmaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def nodes_from_body(
    file_key: str, body: dict[str, Any], node_ids: list[str] | None = None
) -> list[FetchedNode]:
    """Turn a GET /v1/files/:key/nodes response into FetchedNodes.

    Used for live fetches and for saved captures. With ``node_ids``, every one
    must be present; without, all nodes in the response are returned.
    """
    entries = body.get("nodes") or {}
    if node_ids is None:
        node_ids = [n for n, e in entries.items() if e and "document" in e]
    out = []
    for node_id in node_ids:
        entry = entries.get(node_id)
        if not entry or "document" not in entry:
            raise FigmaNotFoundError(404, f"node {node_id} not found in file {file_key}")
        out.append(
            FetchedNode(
                file_key=file_key,
                node_id=node_id,
                file_name=body.get("name", ""),
                version=str(body.get("version", "")),
                last_modified=body.get("lastModified", ""),
                document=entry["document"],
                components=entry.get("components") or {},
                component_sets=entry.get("componentSets") or {},
                styles=entry.get("styles") or {},
            )
        )
    return out


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    message = _error_message(response)
    status = response.status_code
    if status == 429:
        raise FigmaRateLimitError(message, _retry_after(response))
    if status in (401, 403):
        raise FigmaAuthError(status, message)
    if status == 404:
        raise FigmaNotFoundError(status, message)
    raise FigmaAPIError(status, message)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    if isinstance(body, dict):
        return str(body.get("err") or body.get("message") or body)
    return str(body)


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
