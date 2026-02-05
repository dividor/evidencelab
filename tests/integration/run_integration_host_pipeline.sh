#!/bin/bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INTEGRATION_METADATA_FILE="${INTEGRATION_METADATA_FILE:-tests/integration/data/metadata.json}"
INTEGRATION_FILE_PATH="${INTEGRATION_FILE_PATH:-}"
INTEGRATION_FILE_ID="${INTEGRATION_FILE_ID:-}"
API_HEALTH_URL="${API_HEALTH_URL:-http://localhost:8000/health}"
API_BASE_URL="${API_BASE_URL:-http://api:8000}"
UI_BASE_URL="${UI_BASE_URL:-http://ui:3000}"
DATA_SOURCE="${DATA_SOURCE:-uneg}"

echo "Ensuring Qdrant and pipeline are up for integration workflow..."
docker compose up -d --no-deps qdrant pipeline
MAX_ATTEMPTS=60
SLEEP_SECONDS=2
attempt=1
if docker compose exec -T pipeline python - <<'PY' >/dev/null 2>&1
import requests

requests.get("http://qdrant:6333/collections", timeout=2).raise_for_status()
PY
then
  echo "Qdrant is ready."
else
  echo "Waiting for Qdrant (via Docker network)..."
  until docker compose exec -T pipeline python - <<'PY' >/dev/null 2>&1
import requests

requests.get("http://qdrant:6333/collections", timeout=2).raise_for_status()
PY
  do
    if [ "${attempt}" -ge "${MAX_ATTEMPTS}" ]; then
      echo "Qdrant did not become healthy after $((MAX_ATTEMPTS * SLEEP_SECONDS))s."
      exit 1
    fi
    printf "."
    attempt=$((attempt + 1))
    sleep "${SLEEP_SECONDS}"
  done
  echo ""
  echo "Qdrant is ready."
fi

if [ -z "${INTEGRATION_FILE_PATH}" ]; then
  if [ ! -f "${PROJECT_ROOT}/${INTEGRATION_METADATA_FILE}" ]; then
    echo "Missing integration metadata file: ${INTEGRATION_METADATA_FILE}"
    exit 1
  fi
  INTEGRATION_FILE_PATH="$(grep -E '\"file_path\"' "${PROJECT_ROOT}/${INTEGRATION_METADATA_FILE}" | \
    sed -E 's/.*\"file_path\"[[:space:]]*:[[:space:]]*\"([^\"]+)\".*/\1/')"
  if [ -z "${INTEGRATION_FILE_PATH}" ]; then
    echo "metadata.json missing file_path"
    exit 1
  fi
fi

if [ ! -f "${PROJECT_ROOT}/${INTEGRATION_FILE_PATH}" ] && [ ! -f "${INTEGRATION_FILE_PATH}" ]; then
  echo "Integration file not found: ${INTEGRATION_FILE_PATH}"
  exit 1
fi

# Purge any existing integration test document before reingest
echo "Purging integration test document in Docker..."
docker compose exec -T \
  -e DATA_SOURCE="${DATA_SOURCE}" \
  -e INTEGRATION_METADATA_FILE="${INTEGRATION_METADATA_FILE}" \
  pipeline python - <<'PY'
import os

from tests.integration.purge_test_doc import purge_test_document_data

purge_test_document_data(
    data_source=os.environ.get("DATA_SOURCE", "uneg"),
    metadata_path=os.environ.get("INTEGRATION_METADATA_FILE"),
)
PY

if [ -z "${INTEGRATION_FILE_ID}" ]; then
  echo "Resolving integration document ID from file path..."
  INTEGRATION_FILE_ID="$(
    docker compose exec -T \
      -e QDRANT_HOST="http://qdrant:6333" \
      -e INTEGRATION_FILE_PATH="${INTEGRATION_FILE_PATH}" \
      -e DATA_SOURCE="${DATA_SOURCE}" \
      pipeline python - <<'PY'
import os
from pathlib import Path

from pipeline.db import Database
from pipeline.processors.scanning.scanner import _make_relative_path
from pipeline.utilities.id_utils import generate_doc_id

file_path = os.environ["INTEGRATION_FILE_PATH"]
expected_sys_filepath = _make_relative_path(str(Path(file_path).resolve()))
doc_id = generate_doc_id(expected_sys_filepath)

db = Database(data_source=os.environ.get("DATA_SOURCE", "uneg"))
doc = db.get_document(doc_id)
if doc:
    print(doc_id)
PY
  )"
fi

if [ -z "${INTEGRATION_FILE_ID}" ]; then
  echo "Integration document not found in Qdrant. Ingesting by report path."
  echo "Report path: ${INTEGRATION_FILE_PATH}"

  echo "Running host pipeline for integration report: ${INTEGRATION_FILE_PATH}"
  QDRANT_HOST="${QDRANT_HOST:-http://localhost:6333}"
  if ! curl -4 -fsS --max-time 2 "${QDRANT_HOST}/collections" >/dev/null 2>&1; then
    if curl -4 -fsS --max-time 2 "http://host.docker.internal:6333/collections" >/dev/null 2>&1; then
      QDRANT_HOST="http://host.docker.internal:6333"
      export QDRANT_HOST
    else
    echo "❌ Host cannot reach Qdrant at ${QDRANT_HOST}."
    echo "   Ensure the qdrant container port 6333 is exposed or set QDRANT_HOST."
    exit 1
    fi
  fi
  RUN_PIPELINE_ON_HOST=1 \
    QDRANT_HOST="${QDRANT_HOST}" \
    "${PROJECT_ROOT}/scripts/pipeline/run_pipeline_host.sh" \
    --data-source "${DATA_SOURCE}" \
    --report "${INTEGRATION_FILE_PATH}" \
    --skip-download
else
  echo "Resetting document status and clearing chunks for: ${INTEGRATION_FILE_ID}"
  docker compose exec -T \
    -e QDRANT_HOST="http://qdrant:6333" \
    -e INTEGRATION_FILE_ID="${INTEGRATION_FILE_ID}" \
    -e DATA_SOURCE="${DATA_SOURCE}" \
    pipeline python - <<'PY'
import os

from pipeline.db import Database
from qdrant_client.models import FieldCondition, Filter, MatchValue

doc_id = os.environ["INTEGRATION_FILE_ID"]
data_source = os.environ.get("DATA_SOURCE", "uneg")
db = Database(data_source=data_source)

db.client.delete(
    collection_name=db.chunks_collection,
    points_selector=Filter(
        must=[
            FieldCondition(
                key="sys_doc_id", match=MatchValue(value=str(doc_id))
            )
        ]
    ),
)

db.update_document(
    doc_id,
    {
        "sys_status": "downloaded",
        "sys_error_message": None,
        "is_duplicate": False,
    },
    wait=True,
)
PY

  echo "Running host pipeline for integration doc ID: ${INTEGRATION_FILE_ID}"
  QDRANT_HOST="${QDRANT_HOST:-http://localhost:6333}"
  if ! curl -4 -fsS --max-time 2 "${QDRANT_HOST}/collections" >/dev/null 2>&1; then
    if curl -4 -fsS --max-time 2 "http://host.docker.internal:6333/collections" >/dev/null 2>&1; then
      QDRANT_HOST="http://host.docker.internal:6333"
      export QDRANT_HOST
    else
      echo "❌ Host cannot reach Qdrant at ${QDRANT_HOST}."
      echo "   Ensure the qdrant container port 6333 is exposed or set QDRANT_HOST."
      exit 1
    fi
  fi
  RUN_PIPELINE_ON_HOST=1 \
  QDRANT_HOST="${QDRANT_HOST}" \
  INTEGRATION_FILE_ID="${INTEGRATION_FILE_ID}" \
    "${PROJECT_ROOT}/scripts/pipeline/run_pipeline_host.sh"
fi

echo "Restarting docker containers..."
docker compose up -d --build
docker compose up -d embedding-server

echo "Waiting for API to become healthy at ${API_HEALTH_URL}..."
MAX_ATTEMPTS=60
SLEEP_SECONDS=2
attempt=1
until curl -fsS "${API_HEALTH_URL}" >/dev/null 2>&1; do
  if [ "${attempt}" -ge "${MAX_ATTEMPTS}" ]; then
    echo "API did not become healthy after $((MAX_ATTEMPTS * SLEEP_SECONDS))s."
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep "${SLEEP_SECONDS}"
done

echo "Waiting for embedding server on localhost:7997..."
attempt=1
until curl -fsS "http://localhost:7997/health" >/dev/null 2>&1 || \
      curl -fsS "http://localhost:7997" >/dev/null 2>&1; do
  if [ "${attempt}" -ge "${MAX_ATTEMPTS}" ]; then
    echo "Embedding server did not become ready after $((MAX_ATTEMPTS * SLEEP_SECONDS))s."
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep "${SLEEP_SECONDS}"
done

echo "Running integration tests in docker with SKIP_PIPELINE=1..."
docker compose exec -T \
  -e API_BASE_URL="${API_BASE_URL}" \
  -e UI_BASE_URL="${UI_BASE_URL}" \
  -e SKIP_PIPELINE=1 \
  -e SKIP_PURGE=1 \
  pipeline pytest tests/integration -vv
