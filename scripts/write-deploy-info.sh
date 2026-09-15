#!/usr/bin/env bash
# Records what this deploy contains, so chat-bridge can announce it in Slack
# when it starts: a version string, the commits landed since the *previous*
# deploy, and whether the model changed.
#
# The previous deploy's record is what we diff against, so "changes" means
# "since Gary last came up", not "since the beginning of time". Run this
# before `docker compose up` -- restart-gary.sh does it for you.
set -euo pipefail
cd "$(dirname "$0")/.."

INFO=state/deploy-info.json
SHA=$(git rev-parse --short HEAD)
VERSION="$(date +%Y.%m.%d)-${SHA}"
MODEL=$(grep '^OLLAMA_MODEL=' .env | cut -d= -f2-)

PREV_SHA=""
PREV_MODEL=""
if [ -f "$INFO" ]; then
  PREV_SHA=$(python3 -c "import json;print(json.load(open('$INFO')).get('sha',''))" 2>/dev/null || true)
  PREV_MODEL=$(python3 -c "import json;print(json.load(open('$INFO')).get('model',''))" 2>/dev/null || true)
fi

CHANGES=()
if [ -n "$PREV_SHA" ] && git cat-file -e "${PREV_SHA}^{commit}" 2>/dev/null; then
  while IFS= read -r line; do
    [ -n "$line" ] && CHANGES+=("$line")
  done < <(git log --format=%s "${PREV_SHA}..HEAD")
else
  # First deploy, or the recorded commit no longer exists (rebased/pruned).
  CHANGES+=("$(git log -1 --format=%s)")
fi

# .env is gitignored, so a model swap never shows up in git log -- surface it
# explicitly, since it's usually the most consequential thing about a deploy.
# The new model is already in the announcement header, so name the old one
# here rather than repeating it.
if [ -n "$MODEL" ] && [ "$MODEL" != "$PREV_MODEL" ]; then
  if [ -n "$PREV_MODEL" ]; then
    CHANGES+=("Model changed (was: ${PREV_MODEL})")
  else
    CHANGES+=("Model set for the first time on this box")
  fi
fi

if ! git diff --quiet HEAD 2>/dev/null; then
  CHANGES+=("(includes uncommitted local changes)")
fi

mkdir -p state
python3 - "$INFO" "$VERSION" "$SHA" "$MODEL" ${CHANGES[@]+"${CHANGES[@]}"} <<'PY'
import json, sys
info_path, version, sha, model, *changes = sys.argv[1:]
with open(info_path, "w") as fh:
    json.dump({"version": version, "sha": sha, "model": model, "changes": changes},
              fh, indent=2)
PY

echo "deploy-info: v${VERSION}, ${#CHANGES[@]} change(s)"
