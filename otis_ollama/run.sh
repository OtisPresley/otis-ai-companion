#!/bin/bash
set -e

mkdir -p /share/ollama/models
export OLLAMA_MODELS="/share/ollama/models"
export OLLAMA_HOST="0.0.0.0:11434"
export OLLAMA_FLASH_ATTENTION="1"
export OLLAMA_KV_CACHE_TYPE="q8_0"

DEFAULT_MODEL="qwen2.5:1.5b"
KEEP_ALIVE="30m"
NUM_PARALLEL="1"

if [ -f /data/options.json ]; then
    PARSED_MODEL=$(grep -o '"default_model"[[:space:]]*:[[:space:]]*"[^"]*"' /data/options.json | sed 's/.*"default_model"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || true)
    PARSED_KA=$(grep -o '"keep_alive"[[:space:]]*:[[:space:]]*"[^"]*"' /data/options.json | sed 's/.*"keep_alive"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || true)
    PARSED_NP=$(grep -o '"num_parallel"[[:space:]]*:[[:space:]]*[0-9]*' /data/options.json | sed 's/.*"num_parallel"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/' || true)
    [ -n "$PARSED_MODEL" ] && DEFAULT_MODEL="$PARSED_MODEL"
    [ -n "$PARSED_KA" ] && KEEP_ALIVE="$PARSED_KA"
    [ -n "$PARSED_NP" ] && NUM_PARALLEL="$PARSED_NP"
fi

export OLLAMA_KEEP_ALIVE="$KEEP_ALIVE"
export OLLAMA_NUM_PARALLEL="$NUM_PARALLEL"

echo "[Otis Edge AI] Starting Ollama Server on 0.0.0.0:11434 (Models: /share/ollama/models, Default: ${DEFAULT_MODEL}, Keep-Alive: ${KEEP_ALIVE})..."
ollama serve &
SERVER_PID=$!

# Wait for Ollama daemon to accept connections and ensure default model is available
(
    for i in $(seq 1 30); do
        if ollama list >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if [ -n "$DEFAULT_MODEL" ]; then
        if ! ollama list 2>/dev/null | grep -q "^${DEFAULT_MODEL}"; then
            echo "[Otis Edge AI] Pulling default edge model: ${DEFAULT_MODEL}..."
            ollama pull "$DEFAULT_MODEL" || true
        fi
    fi
) &

wait "$SERVER_PID"

