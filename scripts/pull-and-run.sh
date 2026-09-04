#!/usr/bin/env bash
# Run on ANOTHER machine to deploy this stack from your ACR instead of
# building locally. Needs: this repo (or at least docker-compose.yml +
# services/chat-bridge for the build context if you don't push chat-bridge
# separately), .env populated with the ACR-mirrored image refs and secrets,
# az cli logged in, and nvidia-container-toolkit set up (scripts/setup-host.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

if [ -z "${ACR_NAME:-}" ]; then
  echo "ACR_NAME is not set in .env" >&2
  exit 1
fi

az acr login --name "$ACR_NAME"
docker compose pull ollama openhands
docker compose up -d
docker compose ps
