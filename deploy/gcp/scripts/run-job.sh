#!/usr/bin/env bash
# Run the migrate or pipeline job, print its logs, and exit with its result.
#
# Usage: deploy/gcp/scripts/run-job.sh migrate|pipeline [COMMAND...]
#
#   migrate                 Runs alembic upgrade head.
#   pipeline COMMAND...     Runs COMMAND in the pipeline job, for example:
#                           python -m pipeline.orchestrator --data-source demo
#
# The command replaces only the job's arguments for this run: its settings,
# secrets and bucket stay as Terraform defined them. Logs reach Cloud Logging
# a few seconds after the container writes them. Needs terraform, gcloud,
# curl and python3. Set TERRAFORM to run terraform some other way.
set -euo pipefail

job="${1:?usage: run-job.sh migrate|pipeline [COMMAND...]}"
shift
case "$job" in
    migrate | pipeline) ;;
    *) echo "usage: run-job.sh migrate|pipeline [COMMAND...]" >&2; exit 2 ;;
esac
if [ "$job" = pipeline ] && [ "$#" = 0 ]; then
    echo "The pipeline job needs a command, for example: python -m pipeline.orchestrator --help" >&2
    exit 2
fi

here="$(cd "$(dirname "$0")/.." && pwd)"
tf="${TERRAFORM:-terraform}"
output() { $tf -chdir="$here" output -raw "$1"; }

project="$(output project_id)"
region="$(output region)"
job_name="$($tf -chdir="$here" output -json jobs |
    python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$job")"
api="https://run.googleapis.com/v2/projects/$project/locations/$region"
call() {
    curl -fsS -H "Authorization: Bearer $(gcloud auth print-access-token)" \
        -H "Content-Type: application/json" "$@"
}

body="$(python3 -c '
import json, sys
overrides = {"containerOverrides": [{"name": sys.argv[1], "args": sys.argv[2:]}]} if len(sys.argv) > 2 else {}
print(json.dumps({"overrides": overrides}))
' "$job" "$@")"
execution="$(call -X POST "$api/jobs/$job_name:run" -d "$body" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["metadata"]["name"].rsplit("/", 1)[1])')"
echo "Started $job ($execution)"

# Print the execution's log lines that are newer than the last one printed.
last_seen=""
print_new_logs() {
    local filter="resource.type=\"cloud_run_job\" AND labels.\"run.googleapis.com/execution_name\"=\"$execution\""
    if [ -n "$last_seen" ]; then
        filter="$filter AND timestamp>\"$last_seen\""
    fi
    last_seen="$(gcloud logging read "$filter" --project "$project" --order asc --limit 1000 \
        --format json | python3 -c '
import json, sys
entries = json.load(sys.stdin)
for entry in entries:
    print(entry.get("textPayload") or json.dumps(entry.get("jsonPayload")), file=sys.stderr)
print(entries[-1]["timestamp"] if entries else sys.argv[1])
' "$last_seen")"
}

status=""
while :; do
    status="$(call "$api/jobs/$job_name/executions/$execution" | python3 -c '
import json, sys
execution = json.load(sys.stdin)
if execution.get("succeededCount"):
    print("Succeeded")
elif execution.get("failedCount") or execution.get("cancelledCount"):
    print("Failed")
else:
    print("Running")
')"
    print_new_logs
    [ "$status" != Running ] && break
    sleep 15
done

# Wait for the last log lines to reach Cloud Logging.
for _ in 1 2 3; do
    sleep 10
    print_new_logs
done

if [ "$status" != Succeeded ]; then
    echo "$job ($execution) failed." >&2
    exit 1
fi
echo "$job ($execution) succeeded."
