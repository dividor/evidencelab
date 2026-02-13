#!/bin/bash
# scripts/run_pipeline_host.sh
# Runs the pipeline natively on the host machine using the local .venv
# Usage: ./scripts/run_pipeline_host.sh [args]

# Ensure we are in the project root (assuming script is in scripts/)
cd "$(dirname "$0")/../.."

# Load .env if present so required variables are available (e.g., QDRANT_API_KEY).
# Only load lines that look like KEY=VALUE and do not override existing env vars.
if [ -f ".env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ ^[[:space:]]*$ ]] || [[ "$line" =~ ^[[:space:]]*# ]]; then
            continue
        fi
        if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            key="${line%%=*}"
            if [ -z "${!key+x}" ]; then
                export "$line"
            fi
        fi
    done < ".env"
else
    echo "⚠️  Warning: .env not found; using existing environment only."
fi

if [ -n "${DB_DATA_MOUNT:-}" ]; then
    DB_DATA_MOUNT="${DB_DATA_MOUNT%\"}"
    DB_DATA_MOUNT="${DB_DATA_MOUNT#\"}"
    export DB_DATA_MOUNT
fi

# Configuration
VENV_DIR="$HOME/.venvs/evidencelab-ai"
REQUIREMENTS_FILE="requirements.txt"

# 0. Check for System Dependencies
# Auto-detect LibreOffice on macOS if not in PATH
if [[ "$(uname)" == "Darwin" ]] && ! command -v soffice &> /dev/null; then
    if [ -d "/Applications/LibreOffice.app/Contents/MacOS" ]; then
        echo "🍎 Found LibreOffice at default location. Adding to PATH..."
        export PATH="/Applications/LibreOffice.app/Contents/MacOS:$PATH"
    fi
fi

if ! command -v soffice &> /dev/null; then
    echo "❌ Error: 'soffice' (LibreOffice) not found in PATH."
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "   👉 Please install LibreOffice: brew install --cask libreoffice"
    else
        echo "   👉 Please install LibreOffice (e.g., sudo apt install libreoffice)"
    fi
    exit 1
fi

# 1. Automatic Environment Setup
if [ ! -d "$VENV_DIR" ]; then
    echo "⚡️ Virtual environment not found. Creating at $VENV_DIR..."
    mkdir -p "$(dirname "$VENV_DIR")"

    # helper to find python version
    PYTHON_CMD=$(which python3.11 || which python3.10 || which python3)
    echo "   Using Python: $PYTHON_CMD"

    $PYTHON_CMD -m venv "$VENV_DIR"

    echo "📦 Installing base dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip

    # Create a filtered requirements file for Host/Mac to avoid conflicts with Docker pins
    # 1. Remove onnxruntime (Mac needs unpinned/specific version, incompatible with 1.23.2 pin)
    # 2. Remove sentence-transformers (Need to float/patch for infinity-emb)
    grep -vE "onnxruntime|sentence-transformers" "$REQUIREMENTS_FILE" > "$VENV_DIR/requirements_host_filtered.txt"

    "$VENV_DIR/bin/pip" install -r "$VENV_DIR/requirements_host_filtered.txt"
fi

# 2. Activate Environment
echo "🔌 Activating environment..."
export PATH="$VENV_DIR/bin:$PATH"

# 2.1 Validate data directory symlink if DATA_MOUNT_PATH is set
if [ -n "$DATA_MOUNT_PATH" ]; then
    DATA_MOUNT_PATH="${DATA_MOUNT_PATH%\"}"
    DATA_MOUNT_PATH="${DATA_MOUNT_PATH#\"}"
    DATA_DIR="./data"

    # If ./data doesn't exist at all, suggest creating a symlink
    if [ ! -e "$DATA_DIR" ]; then
        echo "❌ Error: $DATA_DIR does not exist."
        echo "   DATA_MOUNT_PATH is set to: $DATA_MOUNT_PATH"
        echo "   Create a symlink so relative paths resolve correctly:"
        echo "   ln -s \"$DATA_MOUNT_PATH\" $DATA_DIR"
        exit 1
    fi

    # If ./data is a symlink, validate it points to DATA_MOUNT_PATH
    if [ -L "$DATA_DIR" ]; then
        LINK_TARGET="$(readlink "$DATA_DIR")"
        if [ "$LINK_TARGET" != "$DATA_MOUNT_PATH" ]; then
            echo "❌ Error: $DATA_DIR symlink target mismatch."
            echo "   Expected: $DATA_MOUNT_PATH"
            echo "   Found:    $LINK_TARGET"
            echo "   Fix with: ln -sf \"$DATA_MOUNT_PATH\" $DATA_DIR"
            exit 1
        fi
    fi
    # If ./data is a regular directory, that's fine - use it as-is
fi

# Set necessary environment variables for Host execution
# - PYTHONUNBUFFERED=1: Force unbuffered stdout for real-time logging
# - EMBEDDING_WORKERS=1: Prevent threading deadlocks in individual workers
# - QDRANT_HOST=localhost: Point to mapped Docker port
# - OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES: Fix multiprocessing interaction on macOS
# Check OS and patch dependencies for Mac MPS (requires legacy stack for optimum/infinity_emb)
if [[ "$(uname)" == "Darwin" ]]; then
    # Upgrade transformers for Docling (rt_detr_v2 support)
    # Remove optimum to avoid "BetterTransformer requires transformers<4.49" error
    # infinity-emb works without optimum (especially on MPS where BetterTransformer is disabled)
    # Install langchain explicitly as it is missing from requirements.txt but needed for summarization
    pip install -q "transformers>=4.50.0" "tokenizers>=0.21.0" "click==8.1.7" "onnxruntime" "sentence-transformers" "infinity-emb[server]>=0.0.77" "langchain" "langchain-community" "langchain-huggingface" "langchain-openai" "langchain-anthropic" "setproctitle"
    pip uninstall -y -q optimum 2>/dev/null || true

    echo "   ✅ Environment prepared."
fi

# Linux host dependency patch (host venv only; does not change requirements.txt)
if [[ "$(uname)" == "Linux" ]]; then
    # Install host-only deps with known-good versions for infinity_emb CLI
    pip install -q \
        "click==8.1.7" \
        "typer==0.12.3" \
        "prometheus-fastapi-instrumentator==6.0.0" \
        "infinity-emb==0.0.77"
    echo "   ✅ Linux host dependencies prepared."
fi

# Disable BetterTransformer via Environment Variable to avoid dependency on optimum
# This prevents infinity_emb from ignoring the missing optimum package and crashing
export INFINITY_BETTERTRANSFORMER=false
echo "DEBUG: INFINITY_BETTERTRANSFORMER=$INFINITY_BETTERTRANSFORMER"

export PYTHONUNBUFFERED=1
export EMBEDDING_WORKERS=1

# Override Qdrant host for local execution if it points to the docker service name
if [[ "$QDRANT_HOST" == *"//qdrant"* ]] || [[ "$QDRANT_HOST" == "qdrant" ]]; then
    echo "⚠️  Detected Docker service name 'qdrant' in QDRANT_HOST. Switching to 'localhost' for host execution."
    export QDRANT_HOST="localhost"
fi

export QDRANT_HOST=${QDRANT_HOST:-localhost}
QDRANT_CURL_AUTH=()
if [ -n "${QDRANT_API_KEY:-}" ]; then
    QDRANT_CURL_AUTH=(-H "api-key: ${QDRANT_API_KEY}")
fi
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

# Stop Docker embedding server to free up system resources
echo "🛑 Stopping Docker embedding server..."
docker compose stop embedding-server || true

echo "🚀 Starting Pipeline on Host..."
echo "Embedding Server: Native (Monitor logs/embedding_server.log)"

# Wait for Qdrant to become reachable from the host.
QDRANT_WAIT_SECS=${QDRANT_WAIT_SECS:-60}
QDRANT_WAIT_INTERVAL=${QDRANT_WAIT_INTERVAL:-2}

normalize_qdrant_url() {
    local host="$1"
    if [[ "$host" != http://* && "$host" != https://* ]]; then
        if [[ "$host" != *:* ]]; then
            host="${host}:6333"
        fi
        host="http://${host}"
    fi
    echo "$host"
}

QDRANT_URL="$(normalize_qdrant_url "$QDRANT_HOST")"
QDRANT_HEALTH_URL="${QDRANT_URL%/}/collections"
echo "⏳ Waiting for Qdrant at $QDRANT_HEALTH_URL (timeout ${QDRANT_WAIT_SECS}s)..."
start_ts=$(date +%s)
while true; do
    if curl -fsS "${QDRANT_CURL_AUTH[@]:-}" "$QDRANT_HEALTH_URL" >/dev/null; then
        echo "   ✅ Qdrant is reachable."
        break
    fi
    now_ts=$(date +%s)
    if (( now_ts - start_ts >= QDRANT_WAIT_SECS )); then
        echo "❌ Error: Qdrant did not become reachable within ${QDRANT_WAIT_SECS}s."
        echo "   Tried: $QDRANT_HEALTH_URL"
        exit 1
    fi
    sleep "$QDRANT_WAIT_INTERVAL"
done

# Run the orchestrator
# We default to --workers 7 and --skip-download if not provided, but allow overrides
# If user provides args, valid args are passed.
# Since we want a "simple command" for the user, let's set sensible defaults if no args.

DEFAULT_DATA_SOURCE="uneg"
DEFAULT_WORKERS=7
DEFAULT_ARGS=(--data-source "$DEFAULT_DATA_SOURCE" --workers "$DEFAULT_WORKERS" --skip-download --skip-scan --recent-first)

if [ $# -eq 0 ]; then
    if [ -n "$INTEGRATION_FILE_ID" ]; then
        echo "Using integration file id: $INTEGRATION_FILE_ID"
        echo "Default configuration: ${DEFAULT_ARGS[*]} --file-id $INTEGRATION_FILE_ID"
        python -m pipeline.orchestrator "${DEFAULT_ARGS[@]}" --file-id "$INTEGRATION_FILE_ID"
    else
        # Default behavior: Process using 'uneg' source, 7 workers, skip download + scan
        echo "Using default configuration: ${DEFAULT_ARGS[*]}"
        python -m pipeline.orchestrator "${DEFAULT_ARGS[@]}"
    fi
else
    # Pass through user arguments
    python -m pipeline.orchestrator "$@"
fi
