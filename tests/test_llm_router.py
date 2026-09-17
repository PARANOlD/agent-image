"""Integration tests: hits the live Ollama server on whatever model is
currently configured (OLLAMA_MODEL). These are classification results from
a real LLM, not fixed logic -- expect occasional drift if the active model
changes, that's the point of running them as part of a delivery check
rather than trusting the swap blind.

Run with: pytest --run-integration
"""
import pytest

from llm_router import route

pytestmark = pytest.mark.integration

# Mirrors app.py's GITHUB_COMMANDS -- duplicated rather than imported so
# this file doesn't pull in app.py's other import-time side effects
# (state.py opens a real sqlite file on import).
GITHUB_COMMANDS = {
    "pr_status": {
        "description": "the status/details of one specific pull request",
        "params": "number (integer, the PR number)",
    },
    "pr_list": {
        "description": "a list of open pull requests",
        "params": "none",
    },
    "create_pr": {
        "description": "cut a branch and open a pull request right now for a described code/file change -- only when explicitly asked to cut a branch or open a PR, not for a general feature request",
        "params": "branch_type: one of feature, bugfix, hotfix (default feature if unclear)",
    },
    "create_ticket": {
        "description": "open a new GitHub issue/ticket to propose and discuss a requested code change before any branch or PR is created -- this is the default for a general feature/change request",
        "params": "none",
    },
    "start_work": {
        "description": "the user has already created a branch themselves and wants Gary to check it out/pull it and start tracking it as the active branch for this conversation, e.g. \"get started on feature/login-fix\"",
        "params": "branch (string, the exact branch name)",
    },
    "open_pr": {
        "description": "open a pull request back to main for the branch already being tracked in this conversation (from a prior start_work) -- e.g. \"create a draft PR for this branch\", \"open a PR to main now\", \"raise the PR\". NOT for cutting a brand new branch (that's create_pr).",
        "params": "draft (boolean; DEFAULT true -- only set false if the message explicitly says the PR should be non-draft/ready for review/active, e.g. \"not draft\", \"mark it ready\", \"make it active\". If the message says nothing about draft/ready status, use true.)",
    },
}


@pytest.mark.parametrize("text,want_command,want_number,want_branch_type", [
    ("what are my active PRs right now?", "pr_list", None, None),
    ("gimme my open pull reqs", "pr_list", None, None),
    ("anything waiting on review?", "pr_list", None, None),
    ("whats the status of PR 1", "pr_status", 1, None),
    ("can you check on pull request number 1 for me", "pr_status", 1, None),
    ("is #1 merged yet", "pr_status", 1, None),
    ("cut a feature branch that adds a LICENSE file", "create_pr", None, "feature"),
    ("can you create a bugfix branch to fix the typo in the readme and raise a PR",
     "create_pr", None, "bugfix"),
    ("raise a hotfix PR that adds a .gitattributes file", "create_pr", None, "hotfix"),
    # create_ticket vs create_pr is the real risk in this registry: a general
    # request should become a ticket to discuss, not an immediate branch/PR.
    ("I'd like to add dark mode support to the config welcome page", "create_ticket", None, None),
    ("can you open a ticket for adding CSV export to the reports page", "create_ticket", None, None),
    ("file an issue about the flaky login redirect", "create_ticket", None, None),
    ("how do I reverse a string in C#", None, None, None),
    ("thanks!", None, None, None),
])
def test_router_classifies_correctly(text, want_command, want_number, want_branch_type):
    result = route(text, GITHUB_COMMANDS)
    assert result["command"] == want_command, f"{text!r} -> {result}"
    if want_number is not None:
        assert result["params"].get("number") == want_number, f"{text!r} -> {result}"
    if want_branch_type is not None:
        assert result["params"].get("branch_type") == want_branch_type, f"{text!r} -> {result}"


@pytest.mark.parametrize("text,want_branch", [
    ("get started on feature/login-fix", "feature/login-fix"),
    ("can you check out and pull bugfix/typo-in-readme", "bugfix/typo-in-readme"),
    ("start working on the branch called feature/dark-mode", "feature/dark-mode"),
])
def test_router_classifies_start_work(text, want_branch):
    result = route(text, GITHUB_COMMANDS)
    assert result["command"] == "start_work", f"{text!r} -> {result}"
    assert result["params"].get("branch") == want_branch, f"{text!r} -> {result}"


@pytest.mark.parametrize("text,want_draft", [
    ("go ahead and create a draft PR for us with this branch to main", True),
    ("open a PR for this branch", True),
    ("raise a PR now, not as draft, we're ready", False),
    ("open the PR to main and make it active, not draft", False),
])
def test_router_classifies_open_pr(text, want_draft):
    result = route(text, GITHUB_COMMANDS)
    assert result["command"] == "open_pr", f"{text!r} -> {result}"
    assert result["params"].get("draft") == want_draft, f"{text!r} -> {result}"


def test_router_falls_back_safely_on_garbage_commands():
    # An empty registry should never match anything, regardless of text.
    assert route("anything at all", {}) == {"command": None, "params": {}}
