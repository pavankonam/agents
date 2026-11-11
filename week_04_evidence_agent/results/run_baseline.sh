#!/usr/bin/env bash
# Record the real model baseline for week 04 and rebuild results/RESULTS.md (D39).
# Run from week_04_evidence_agent/ with Ollama up:  bash results/run_baseline.sh [model] [seeds]
set -euo pipefail
MODEL="${1:-qwen3:4b}"
SEEDS="${2:-3}"
SLUG="$(echo "$MODEL" | tr ':/.' '___')"
export PYTHONPATH=src
python3 -m evidence_agent check --model "$MODEL"
python3 -m evidence_agent eval --model "$MODEL" --seeds "$SEEDS" \
  --record "results/${SLUG}_eval.jsonl" --min-pass-rate 0 || true
files=(results/*_eval.jsonl)
python3 -m evidence_agent report "${files[@]}" --markdown > results/RESULTS.md
echo "wrote results/${SLUG}_eval.jsonl and results/RESULTS.md"
