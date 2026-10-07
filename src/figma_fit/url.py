"""Parse Figma URLs into the (file_key, node_id) pair the REST API wants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

_HOSTS = {"figma.com", "www.figma.com"}
_DESIGN_KINDS = {"design", "file", "proto"}
_UNSUPPORTED_KINDS = {
    "board": "FigJam boards are not supported yet",
    "slides": "Figma Slides files are not supported yet",
    "make": "Figma Make files are not supported yet",
    "deck": "Figma Slides files are not supported yet",
}
# Plain ids ("1:2") and instance-sublayer ids ("I1:2;3:4").
_NODE_ID = re.compile(r"^I?\d+:\d+(;\d+:\d+)*$")


class FigmaURLError(ValueError):
    """The URL is not a Figma design link we can fetch."""


@dataclass(frozen=True)
class FigmaRef:
    file_key: str
    node_id: str  # API form, e.g. "1:2"


def parse_figma_url(url: str) -> FigmaRef:
    """Return the file key and node id for a Figma design URL.

    Branch URLs resolve to the branch key. A node id is required: fetching a
    whole file is exactly the case that blows past every budget.
    """
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)

    if parts.hostname not in _HOSTS:
        raise FigmaURLError(f"not a figma.com URL: {url!r}")

    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        raise FigmaURLError(f"no file key in URL: {url!r}")

    kind, file_key = segments[0], segments[1]
    if kind in _UNSUPPORTED_KINDS:
        raise FigmaURLError(_UNSUPPORTED_KINDS[kind])
    if kind not in _DESIGN_KINDS:
        raise FigmaURLError(f"unrecognised Figma URL type {kind!r}: {url!r}")

    if len(segments) >= 4 and segments[2] == "branch":
        file_key = segments[3]

    raw_ids = parse_qs(parts.query).get("node-id")
    if not raw_ids or not raw_ids[0]:
        raise FigmaURLError(
            "URL has no node-id. Right-click a frame in Figma and use "
            "'Copy link to selection' so only that frame is fetched."
        )

    return FigmaRef(file_key=file_key, node_id=normalize_node_id(raw_ids[0]))


def normalize_node_id(node_id: str) -> str:
    """Convert a URL-style node id ("1-2") to API form ("1:2")."""
    api_id = node_id.strip().replace("-", ":")
    if not _NODE_ID.match(api_id):
        raise FigmaURLError(f"invalid node id: {node_id!r}")
    return api_id
