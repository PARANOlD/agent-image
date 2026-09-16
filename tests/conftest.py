import sys
from pathlib import Path

import pytest

# Tests import chat-bridge's modules directly rather than duplicating logic;
# this is the only path-setup needed since those modules have no package
# structure of their own.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "chat-bridge"))


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration", action="store_true", default=False,
        help="also run tests marked 'integration' (need a live Ollama server, slower)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="needs --run-integration (live Ollama server)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
