#!/usr/bin/env bash
# Runs Gary's test suite inside the chat-bridge image, so it always tests
# against the exact code/deps that get shipped -- not whatever happens to
# be on the host.
#
# Default: fast unit tests only (no network, no model). Add --run-integration
# to also exercise the live classifiers (llm_router, intent_gate) against
# whatever model is currently configured -- requires ollama already running.
#
# Usage: ./scripts/run-tests.sh [pytest args...]
#   ./scripts/run-tests.sh                        # unit tests only
#   ./scripts/run-tests.sh --run-integration       # everything, needs ollama up
#   ./scripts/run-tests.sh -k pr_list              # any pytest args pass through
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose run --rm --no-deps \
  -v "$(pwd)/tests:/app/tests:ro" \
  -v "$(pwd)/pytest.ini:/app/pytest.ini:ro" \
  -T chat-bridge python -m pytest "$@"
