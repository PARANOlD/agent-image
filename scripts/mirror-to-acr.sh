#!/usr/bin/env bash
# Retags every image this stack uses (including our own chat-bridge build)
# under <ACR_NAME>.azurecr.io and pushes them, so other machines only ever
# need to pull from your ACR. Does NOT run az login for you.
#
# Usage: ./scripts/mirror-to-acr.sh [tag]
#   tag defaults to the current git short SHA.
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

if [ -z "${ACR_NAME:-}" ]; then
  echo "ACR_NAME is not set in .env" >&2
  exit 1
fi

TAG="${1:-$(git rev-parse --short HEAD)}"
REGISTRY="${ACR_NAME}.azurecr.io"

echo "== az acr login (will prompt if not already authenticated) =="
az acr login --name "$ACR_NAME"

echo "== Building chat-bridge =="
docker compose build chat-bridge

echo "== Running unit tests (fast, no live model needed) =="
./scripts/run-tests.sh
echo "   (skipped: integration tests, which need a live Ollama on the target"
echo "   model -- run './scripts/run-tests.sh --run-integration' yourself if"
echo "   you want classifier behavior checked before shipping too)"

mirror() {
  local src="$1" name="$2"
  local dst="${REGISTRY}/${name}:${TAG}"
  docker tag "$src" "$dst"
  docker push "$dst"
  echo "  pushed $dst"
}

mirror "${OLLAMA_IMAGE:-ollama/ollama:latest}" "ollama"
mirror "${OPENHANDS_IMAGE:-ghcr.io/openhands/agent-server:1.26.0-python}" "openhands"
mirror "gary-chat-bridge:local" "chat-bridge"

echo "== Done. Tagged as :${TAG} in ${REGISTRY} =="
echo "Update deploy .env on target machines with these image refs, or point"
echo "OLLAMA_IMAGE / OPENHANDS_IMAGE at ${REGISTRY}/...:${TAG}"
