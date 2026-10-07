import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def pricing_body() -> dict:
    return json.loads((FIXTURES / "pricing_nodes.json").read_text())
