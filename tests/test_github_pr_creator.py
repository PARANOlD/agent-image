"""create_branch_and_pr() itself isn't tested here automatically -- it
pushes a real branch and opens a real PR against a real repo, which isn't
something to run on every test invocation. It was validated manually
against PARANOlD/prototyping (PR #2) before this shipped. What's covered
here: input validation (no model/network), and the two LLM calls that
feed it (integration, live model)."""
import pytest

from github_pr_creator import PrCreationError, _generate_metadata, create_branch_and_pr

pytestmark_integration = pytest.mark.integration


def test_invalid_branch_type_rejected_without_any_network_call():
    with pytest.raises(PrCreationError) as exc_info:
        create_branch_and_pr(auth=None, repo="owner/repo", branch_type="release", description="anything")
    for word in ("feature", "bugfix", "hotfix"):
        assert word in str(exc_info.value)


@pytest.mark.integration
def test_generate_metadata_produces_usable_fields():
    meta = _generate_metadata(
        "feature", "add a CONTRIBUTING.md file explaining how to submit a pull request to this repo"
    )
    assert meta["filename"]
    assert meta["commit_message"]
    assert meta["pr_title"]
    assert meta["pr_body"]
    # Slug must already be sanitized: lowercase, hyphenated, no stray chars.
    assert meta["slug"] == meta["slug"].lower()
    assert " " not in meta["slug"]
    assert all(c.isalnum() or c == "-" for c in meta["slug"])
