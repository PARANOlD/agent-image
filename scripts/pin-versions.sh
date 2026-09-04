#!/usr/bin/env bash
# Resolves the ollama/openhands image tags to content digests and writes
# them into .env, so the stack is reproducible even if the upstream tag
# later moves. Run after changing OLLAMA_BASE_TAG / OPENHANDS_BASE_TAG below
# if you want to re-pin to a newer release.
set -euo pipefail
cd "$(dirname "$0")/.."

OLLAMA_BASE_TAG="${OLLAMA_BASE_TAG:-ollama/ollama:latest}"
# ghcr.io/openhands/agent-server doesn't reliably publish :latest -- pin an
# explicit release tag here and bump it deliberately.
OPENHANDS_BASE_TAG="${OPENHANDS_BASE_TAG:-ghcr.io/openhands/agent-server:1.26.0-python}"

pin() {
  local ref="$1"
  docker pull "$ref" >/dev/null
  docker inspect --format='{{index .RepoDigests 0}}' "$ref"
}

echo "Resolving ${OLLAMA_BASE_TAG} ..."
OLLAMA_PINNED=$(pin "$OLLAMA_BASE_TAG")
echo "  -> $OLLAMA_PINNED"

echo "Resolving ${OPENHANDS_BASE_TAG} ..."
OPENHANDS_PINNED=$(pin "$OPENHANDS_BASE_TAG")
echo "  -> $OPENHANDS_PINNED"

# Update .env in place (create the keys if missing).
touch .env
for kv in "OLLAMA_IMAGE=$OLLAMA_PINNED" "OPENHANDS_IMAGE=$OPENHANDS_PINNED"; do
  key="${kv%%=*}"
  if grep -q "^${key}=" .env; then
    sed -i "s#^${key}=.*#${kv}#" .env
  else
    echo "$kv" >> .env
  fi
done

echo "Pinned versions written to .env."
