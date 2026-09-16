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

# Mirrors app.py's PR_COMMANDS -- duplicated rather than imported so this
# file doesn't pull in app.py's other import-time side effects (state.py
# opens a real sqlite file on import).
PR_COMMANDS = {
    "pr_status": {
        "description": "the status/details of one specific pull request",
        "params": "number (integer, the PR number)",
    },
    "pr_list": {
        "description": "a list of open pull requests",
        "params": "none",
    },
    "create_pr": {
        "description": "cut a branch and open a pull request for a described code/file change",
        "params": "branch_type: one of feature, bugfix, hotfix (default feature if unclear)",
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
    ("how do I reverse a string in C#", None, None, None),
    ("thanks!", None, None, None),
])
def test_router_classifies_correctly(text, want_command, want_number, want_branch_type):
    result = route(text, PR_COMMANDS)
    assert result["command"] == want_command, f"{text!r} -> {result}"
    if want_number is not None:
        assert result["params"].get("number") == want_number, f"{text!r} -> {result}"
    if want_branch_type is not None:
        assert result["params"].get("branch_type") == want_branch_type, f"{text!r} -> {result}"


def test_router_falls_back_safely_on_garbage_commands():
    # An empty registry should never match anything, regardless of text.
    assert route("anything at all", {}) == {"command": None, "params": {}}
