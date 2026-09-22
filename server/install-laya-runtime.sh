#!/bin/zsh
# Install the local Laya package and multilingual checkpoint used by the router.
# This script does not read Codex, ChatGPT, TypeSafe, or Hugging Face tokens.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LAYA_ROOT="${LAYA_ROOT:-$REPO/../laya}"
LAYA_REPO="${LAYA_REPO:-https://github.com/NandhaKishorM/laya.git}"
PYTHON="${PYTHON:-$(command -v python3)}"

if [ ! -d "$LAYA_ROOT/.git" ]; then
  git clone "$LAYA_REPO" "$LAYA_ROOT"
else
  if [ -z "$(git -C "$LAYA_ROOT" status --porcelain)" ]; then
    git -C "$LAYA_ROOT" pull --ff-only
  else
    echo "Laya checkout has local changes; keeping the existing checkout."
  fi
fi

if [ ! -x "$LAYA_ROOT/.venv/bin/python" ]; then
  "$PYTHON" -m venv "$LAYA_ROOT/.venv"
fi

"$LAYA_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$LAYA_ROOT/.venv/bin/python" -m pip install -e "$LAYA_ROOT"

LAYA_ROOT="$LAYA_ROOT" "$LAYA_ROOT/.venv/bin/python" - <<'PY'
import os
from huggingface_hub import snapshot_download

root = os.environ["LAYA_ROOT"]
snapshot_download(
    "convaiinnovations/laya",
    allow_patterns=[
        "multilingual/rl_agent_config.json",
        "multilingual/model.safetensors",
        "multilingual/tokenizer/*",
        "multilingual/encoder/*",
    ],
    local_dir=os.path.join(root, "models"),
)
PY

LAYA_ROOT="$LAYA_ROOT" "$LAYA_ROOT/.venv/bin/python" - <<'PY'
import os
import laya

model_path = os.path.join(os.environ["LAYA_ROOT"], "models", "multilingual")
agent = laya.load(model_path, device="cpu")
questions = {"route": {
    "type": "choice",
    "instructions": "Choose the sufficient tier.",
    "criteria": {"small": "simple task", "large": "complex task"},
}}
result = agent.predict({"task": "Say OK"}, questions)
assert result["answers"]["route"]["choice"] in {"small", "large"}
print(f"Laya runtime OK: {model_path}")
PY
