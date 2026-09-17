"""Pure unit tests: formatting logic only, no network/model involved.
Fast -- these should run on every build."""
from github_actions import format_branch_status, format_pr_list, format_pr_status, get_pr_for_branch, mark_pr_ready

OPEN_PR = {
    "title": "Add Next.js welcome page for Gary configuration",
    "state": "open",
    "merged": False,
    "draft": False,
    "user": {"login": "gary-assistant[bot]"},
    "head": {"ref": "gary/nextjs-config-welcome"},
    "base": {"ref": "main"},
    "mergeable_state": "clean",
    "html_url": "https://github.com/PARANOlD/prototyping/pull/1",
}


def test_format_pr_status_open():
    text = format_pr_status("PARANOlD/prototyping", 1, OPEN_PR)
    assert "PR #1" in text
    assert "Status: open" in text
    assert "gary-assistant[bot]" in text
    assert "gary/nextjs-config-welcome" in text
    assert "https://github.com/PARANOlD/prototyping/pull/1" in text


def test_format_pr_status_merged():
    merged = {**OPEN_PR, "merged": True}
    text = format_pr_status("owner/repo", 5, merged)
    assert "Status: merged" in text


def test_format_pr_status_draft():
    draft = {**OPEN_PR, "draft": True}
    text = format_pr_status("owner/repo", 5, draft)
    assert "Status: draft" in text


def test_format_pr_status_not_found():
    text = format_pr_status("owner/repo", 99, None)
    assert "Couldn't find PR #99" in text
    assert "owner/repo" in text


def test_format_pr_list_with_results():
    text = format_pr_list("PARANOlD/prototyping", [OPEN_PR | {"number": 1}])
    assert "Open PRs in PARANOlD/prototyping" in text
    # Standard markdown link, not Slack's old <url|text> mrkdwn syntax --
    # regression check for a real bug caught before shipping (2026-09-16).
    assert "[#1](https://github.com/PARANOlD/prototyping/pull/1)" in text
    assert "<" not in text.split("\n", 1)[1]  # no leftover mrkdwn angle brackets


def test_format_pr_list_empty():
    text = format_pr_list("owner/repo", [])
    assert "No open PRs in owner/repo" in text


def test_format_pr_list_lookup_failed():
    text = format_pr_list("owner/repo", None)
    assert "Couldn't list PRs" in text


BRANCH = {
    "name": "feature/login-fix",
    "commit": {
        "sha": "e41b8b25fc58989f208e67cdaa2081d3943a0dca",
        "commit": {"message": "Fix login redirect loop\n\nCo-authored-by: someone"},
    },
}


def test_format_branch_status_found():
    text = format_branch_status("owner/repo", "feature/login-fix", BRANCH)
    assert "feature/login-fix" in text
    assert "e41b8b2" in text
    assert "Fix login redirect loop" in text
    assert "Co-authored-by" not in text  # only the commit's first line


def test_format_branch_status_not_found():
    text = format_branch_status("owner/repo", "feature/missing", None)
    assert "Couldn't find branch" in text
    assert "feature/missing" in text


def test_get_pr_for_branch_fails_safe_without_a_real_network_call():
    # auth=None makes auth.get_token() raise inside the try/except -- should
    # come back as None, not an unhandled traceback.
    assert get_pr_for_branch(auth=None, repo="owner/repo", branch="feature/missing") is None


def test_mark_pr_ready_fails_safe_without_a_real_network_call():
    assert mark_pr_ready(auth=None, node_id="PR_fake") is False
