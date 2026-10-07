import pytest

from figma_fit.url import FigmaRef, FigmaURLError, normalize_node_id, parse_figma_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.figma.com/design/AbC123xyz/My-File?node-id=1-2&t=abc-0",
            FigmaRef("AbC123xyz", "1:2"),
        ),
        (
            "https://figma.com/design/AbC123xyz/My-File?node-id=12-345",
            FigmaRef("AbC123xyz", "12:345"),
        ),
        ("https://www.figma.com/file/LegacyKey/Old-File?node-id=0-1", FigmaRef("LegacyKey", "0:1")),
        (
            "https://www.figma.com/proto/ProtoKey/Flow?node-id=4-5&scaling=min-zoom",
            FigmaRef("ProtoKey", "4:5"),
        ),
        (
            "https://www.figma.com/design/MainKey/branch/BranchKey/My-File?node-id=7-8",
            FigmaRef("BranchKey", "7:8"),
        ),
        (
            "https://www.figma.com/design/AbC123xyz/My-File?node-id=1%3A2",
            FigmaRef("AbC123xyz", "1:2"),
        ),
        ("figma.com/design/AbC123xyz/My-File?node-id=1-2", FigmaRef("AbC123xyz", "1:2")),
        ("  https://www.figma.com/design/AbC123xyz?node-id=1-2  ", FigmaRef("AbC123xyz", "1:2")),
        (
            "https://www.figma.com/design/AbC123xyz/F?node-id=I1-2%3B3-4",
            FigmaRef("AbC123xyz", "I1:2;3:4"),
        ),
    ],
)
def test_parses_design_urls(url, expected):
    assert parse_figma_url(url) == expected


@pytest.mark.parametrize(
    ("url", "match"),
    [
        ("https://www.figma.com/design/AbC123xyz/My-File", "no node-id"),
        ("https://www.figma.com/design/AbC123xyz/My-File?node-id=", "no node-id"),
        ("https://www.figma.com/board/BoardKey/Jam?node-id=1-2", "FigJam"),
        ("https://www.figma.com/slides/SlideKey/Deck?node-id=1-2", "Slides"),
        ("https://www.figma.com/make/MakeKey/App", "Make"),
        ("https://example.com/design/AbC123xyz/My-File?node-id=1-2", "not a figma.com URL"),
        ("https://www.figma.com/community/file/123", "unrecognised"),
        ("https://www.figma.com/design", "no file key"),
        ("https://www.figma.com/design/AbC123xyz/F?node-id=abc", "invalid node id"),
    ],
)
def test_rejects_unusable_urls(url, match):
    with pytest.raises(FigmaURLError, match=match):
        parse_figma_url(url)


def test_normalize_node_id_accepts_api_form():
    assert normalize_node_id("1:2") == "1:2"
