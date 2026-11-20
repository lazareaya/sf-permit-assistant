#!/usr/bin/env bash
# Full evaluation: SF permit assistant vs. single-prompt baseline, 25 scenarios,
# LLM-as-a-judge. Needs a Gemini backend in .env (GEMINI_API_KEY or a GCP project)
# and the official pages indexed in data/city_docs/.
#
#   bash scripts/run_eval.sh
#
# 1. serves both agents (app + baseline) on a COPY of the projects DB
# 2. 23 scenarios with the real DataSF API, then 2 with DataSF "down"
#    (unreachable URL, cache off)
# 3. grades the traces (agents-cli eval grade) and compares (agents-cli eval compare)
# 4. writes docs/eval_results.md and the README table
set -euo pipefail
cd "$(dirname "$0")/.."

ACLI="uvx google-agents-cli"
PORT=8010
WORK=$(mktemp -d)
OUT=artifacts/eval_$(date +%Y%m%d_%H%M%S)
mkdir -p "$OUT"
cp data/projects.db "$WORK/projects.db"
trap 'kill ${SERVER:-} 2>/dev/null || true' EXIT

wait_http() { for _ in $(seq 1 60); do curl -sf "$1" >/dev/null && return 0; sleep 1; done; echo "timeout $1"; return 1; }

serve() {  # $1 = DataSF url, $2 = cache on/off
  PROJECTS_DB_PATH="$WORK/projects.db" DATASF_URL="$1" DATASF_CACHE="$2" \
    DATASF_CACHE_PATH="$WORK/datasf.sqlite" CHROMA_DIR="$WORK/chroma" \
    uv run uvicorn app.fast_api_app:app --port $PORT >"$WORK/agent_$2.log" 2>&1 &
  SERVER=$!
  wait_http "http://localhost:$PORT/list-apps"
}

for phase in main down; do
  if [ "$phase" = main ]; then serve "https://data.sf.gov/resource/i98e-djp9.json" on; DS=tests/eval/datasets/sf-permit-scenarios.json
  else serve "http://127.0.0.1:9/resource.json" off; DS=tests/eval/datasets/datasf-down.json; fi
  for agent in app baseline; do
    echo ">> generate $agent / $phase"
    $ACLI eval generate --url "http://localhost:$PORT" --app-name "$agent" \
      --dataset "$DS" --output "$OUT/traces/$agent/$phase.json" --concurrency 4
  done
  kill "$SERVER"; wait "$SERVER" 2>/dev/null || true
done

for agent in app baseline; do
  echo ">> grade $agent"
  $ACLI eval grade --traces "$OUT/traces/$agent" --config tests/eval/eval_config.yaml \
    --output "$OUT/grades/$agent" --qps 2 || true   # baseline may fail the threshold
done

BASE=$(ls "$OUT"/grades/baseline/results_*.json | head -1)
CAND=$(ls "$OUT"/grades/app/results_*.json | head -1)
$ACLI eval compare "$BASE" "$CAND" | tee "$OUT/compare.txt"
uv run python scripts/summarize_eval.py --agent "$CAND" --baseline "$BASE" --out docs/eval_results.md
echo ">> done: $OUT and docs/eval_results.md"
