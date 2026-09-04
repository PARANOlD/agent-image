#!/usr/bin/env bash
# Mints a fresh GitHub App installation token (valid ~1hr) for the openhands
# container's own git operations, writes it into .env as GITHUB_TOKEN, and
# restarts openhands to pick it up. Re-run this whenever git push/clone in
# the sandbox starts failing with an auth error.
set -euo pipefail
cd "$(dirname "$0")/.."

TOKEN=$(docker compose run --rm --no-deps chat-bridge python mint_token.py)

if grep -q '^GITHUB_TOKEN=' .env; then
  sed -i "s#^GITHUB_TOKEN=.*#GITHUB_TOKEN=${TOKEN}#" .env
else
  echo "GITHUB_TOKEN=${TOKEN}" >> .env
fi

docker compose up -d openhands
echo "GITHUB_TOKEN refreshed and openhands restarted."
