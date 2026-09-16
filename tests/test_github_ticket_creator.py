"""create_ticket() itself isn't tested here automatically -- it opens a real
issue against a real repo. What's covered: the one LLM call that feeds it
(integration, live model)."""
import pytest

from github_ticket_creator import _generate_issue_metadata

pytestmark = pytest.mark.integration


def test_generate_issue_metadata_produces_usable_fields():
    meta = _generate_issue_metadata(
        "add dark mode support to the config welcome page"
    )
    assert meta["title"]
    assert meta["body"]
