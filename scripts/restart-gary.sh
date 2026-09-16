#!/usr/bin/env bash
# Full restart of the Gary stack -- as close to a reboot as you can get
# without one. Tears containers down completely (which is what actually
# releases the VRAM/RAM ollama is holding; `restart` does not), checks the
# GPU is genuinely usable, brings everything back, and confirms the model
# loaded onto the GPU instead of silently falling back to CPU.
#
# That last check matters: a driver/library mismatch (kernel module updated
# without a reboot) doesn't fail loudly -- ollama just runs the model at
# 100% CPU, which for a 14B model means multi-minute responses and RAM
# exhaustion. Cost us a debugging session on 2026-09-15.
#
# Usage: ./scripts/restart-gary.sh [--no-warm]
set -euo pipefail
cd "$(dirname "$0")/.."

WARM=1
[ "${1:-}" = "--no-warm" ] && WARM=0

MODEL=$(grep '^OLLAMA_MODEL=' .env | cut -d= -f2-)
API_KEY=$(grep '^OPENHANDS_API_KEY=' .env | cut -d= -f2-)

echo "== Tearing down (releases GPU/host memory held by ollama) =="
docker compose down --remove-orphans

echo
echo "== GPU check =="
if ! nvidia-smi --query-gpu=name,memory.used,memory.total,driver_version --format=csv; then
  echo
  echo "!! nvidia-smi failed. If this says 'Driver/library version mismatch',"
  echo "!! a driver update landed without a reboot -- the loaded kernel module"
  echo "!! and the userspace libraries disagree. REBOOT before starting Gary,"
  echo "!! otherwise he will run entirely on CPU without telling you."
  exit 1
fi

echo
echo "== Recording deploy info (drives Gary's Slack announcement) =="
# Tolerated, not fatal: write-deploy-info.sh refuses to run on an uncommitted
# tree (see its own comment -- that used to silently produce a misleading
# announcement instead). Testing local changes before committing is a normal
# workflow, so a dirty tree here just means the *next* commit's restart will
# pick up the accumulated changes; it must not block bringing the stack up.
./scripts/write-deploy-info.sh || echo "   (skipped -- uncommitted changes; stack still starting)"

echo
echo "== Starting stack =="
docker compose up -d

echo
echo "== Waiting for services =="
for i in $(seq 1 60); do
  healthy=$(docker compose ps --format json 2>/dev/null \
    | python3 -c "
import json,sys
ok=0
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: svc=json.loads(line)
    except ValueError: continue
    if svc.get('Health') in ('healthy','') and svc.get('State')=='running': ok+=1
print(ok)
" 2>/dev/null || echo 0)
  [ "$healthy" -ge 3 ] && break
  sleep 2
done
docker compose ps

if [ "$WARM" = "0" ]; then
  echo
  echo "== Done (skipped model warm-up; GPU placement unverified) =="
  exit 0
fi

echo
echo "== Warming $MODEL and verifying it landed on the GPU =="
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" \
  > /dev/null || { echo "!! ollama did not respond"; exit 1; }

PLACEMENT=$(docker compose exec -T ollama ollama ps | tail -n +2)
echo "$PLACEMENT"

if echo "$PLACEMENT" | grep -q "CPU"; then
  echo
  echo "!! Model is running (at least partly) on CPU, not the GPU."
  echo "!! Expect very slow responses. Check nvidia-smi, the nvidia container"
  echo "!! runtime, and whether the model fits in VRAM alongside the context"
  echo "!! length set by OLLAMA_CONTEXT_LENGTH."
  exit 1
fi

echo
echo "== Gary is up, model on GPU =="
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
