#!/usr/bin/env bash
# Full evaluation: fraud analyst agent vs. single-prompt baseline, 25 scenarios,
# LLM-as-a-judge. Needs a Gemini backend in .env (GEMINI_API_KEY or a GCP project).
#
#   bash scripts/run_eval.sh
#
# 1. starts the Project 2 fraud API if it is not running (FRAUD_API_URL)
# 2. serves both agents (app + baseline) on a COPY of the bank DB
# 3. 22 normal scenarios, then 3 scenarios with the fraud API down
# 4. grades the traces (agents-cli eval grade) and compares (agents-cli eval compare)
# 5. writes docs/eval_results.md
set -euo pipefail
cd "$(dirname "$0")/.."

ACLI="uvx google-agents-cli"
PORT=8010
FRAUD_API_URL="${FRAUD_API_URL:-http://localhost:8001}"
P2_DIR="${P2_DIR:-../../PROJET 2 - ML /fraud-detection-mlops}"
WORK=$(mktemp -d)
OUT=artifacts/eval_$(date +%Y%m%d_%H%M%S)
mkdir -p "$OUT"
cp data/bank.db "$WORK/bank.db"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

wait_http() { for _ in $(seq 1 60); do curl -sf "$1" >/dev/null && return 0; sleep 1; done; echo "timeout $1"; return 1; }

if ! curl -sf "$FRAUD_API_URL/health" >/dev/null; then
  echo ">> starting Project 2 fraud API from $P2_DIR"
  ( cd "$P2_DIR" && MLOPS_DATASET=creditcard \
      MODEL_URI="$(pwd)/$(python3 -c "import json;print('mlruns/1/'+json.load(open('models/creditcard/run_info.json'))['run_id']+'/artifacts/model')")" \
      MLFLOW_TRACKING_URI="sqlite:///mlflow-data/mlflow.db" PREDICTION_LOG_PATH="$WORK/pred.jsonl" \
      .venv/bin/uvicorn api.main:app --port 8001 >"$WORK/fraud_api.log" 2>&1 ) &
  PIDS+=($!)
  wait_http "$FRAUD_API_URL/health"
fi

serve() {  # $1 = fraud API url
  BANK_DB_PATH="$WORK/bank.db" FRAUD_API_URL="$1" CHROMA_DIR="$WORK/chroma" \
    uv run uvicorn app.fast_api_app:app --port $PORT >"$WORK/agent_$PORT.log" 2>&1 &
  SERVER=$!
  wait_http "http://localhost:$PORT/list-apps"
}

for phase in main down; do
  if [ "$phase" = main ]; then serve "$FRAUD_API_URL"; DS=tests/eval/datasets/fraud-scenarios.json
  else serve "http://127.0.0.1:9"; DS=tests/eval/datasets/fraud-api-down.json; fi
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
