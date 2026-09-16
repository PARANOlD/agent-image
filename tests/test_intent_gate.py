"""Integration tests: hits the live Ollama server. Guards against the real
regression this shipped once already -- the gate silently dropped messages
that plainly addressed Gary by name (see intent_gate.py's module docstring
and the 2026-09-15 fix). The name-match case doesn't call the model at all;
the rest do.

Run with: pytest --run-integration
"""
import pytest

from intent_gate import is_directed_at_gary

pytestmark = pytest.mark.integration

BABBAGE_REPLY = "The first computer was built by Charles Babbage around 1837."
CODE_REPLY = (
    'Use the Array.Reverse method:\n```csharp\nstring original = "hello";\n'
    "char[] a = original.ToCharArray();\nArray.Reverse(a);\n```"
)


def test_name_match_short_circuits_without_a_model_call():
    # No last_reply given at all -- if this needed the model it would error
    # (no Ollama config here), so passing proves the name check runs first.
    assert is_directed_at_gary("Gary who built the first computer?") is True


@pytest.mark.parametrize("text,last_reply,want", [
    ("what about the first electronic one?", BABBAGE_REPLY, True),
    ("thanks, that worked", BABBAGE_REPLY, True),
    ("bob did you see the game last night", BABBAGE_REPLY, False),
    ("@dave can you review my PR when you get a sec", BABBAGE_REPLY, False),
    ("can you make that async instead?", CODE_REPLY, True),
    ("now add error handling", CODE_REPLY, True),
    ("does that handle null?", CODE_REPLY, True),
])
def test_gate_uses_thread_context(text, last_reply, want):
    assert is_directed_at_gary(text, last_reply=last_reply) is want
