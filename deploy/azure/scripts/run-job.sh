#!/usr/bin/env bash
# Run the migrate or pipeline job, print its logs, and exit with its result.
#
# Usage: deploy/azure/scripts/run-job.sh migrate|pipeline [COMMAND...]
#
#   migrate                 Runs alembic upgrade head.
#   pipeline COMMAND...     Runs COMMAND in the pipeline job, for example:
#                           python -m pipeline.orchestrator --data-source demo
#
# The pipeline command is stored on the job before it starts. A command given
# when starting a job replaces the job's whole container, settings and file
# share included, so this keeps everything else as Terraform defined it. Run
# one pipeline command at a time.
#
# Logs reach Log Analytics a few minutes after the container writes them, so
# they appear in batches. Needs terraform, the az CLI and python3. Set
# TERRAFORM to run terraform some other way.
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

workspace="$(output log_workspace_id)"
job_url="https://management.azure.com$($tf -chdir="$here" output -json job_ids |
    python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$job")"
api="api-version=2026-01-01"

if [ "$#" -gt 0 ]; then
    body="$(mktemp)"
    trap 'rm -f "$body"' EXIT
    az rest --method get --url "$job_url?$api" --output json |
        python3 -c '
import json, sys
template = json.load(sys.stdin)["properties"]["template"]
template["containers"][0]["args"] = sys.argv[2:]
json.dump({"properties": {"template": template}}, open(sys.argv[1], "w"))
' "$body" "$@"
    az rest --method patch --url "$job_url?$api" --body "@$body" --output none
    # The update finishes in the background; start only once it has.
    for attempt in $(seq 1 60); do
        state="$(az rest --method get --url "$job_url?$api" --output json |
            python3 -c '
import json, sys
job = json.load(sys.stdin)["properties"]
print(job["provisioningState"] == "Succeeded" and job["template"]["containers"][0].get("args") == sys.argv[1:])
' "$@")"
        [ "$state" = True ] && break
        if [ "$attempt" = 60 ]; then
            echo "The $job job did not take the new command within 5 minutes." >&2
            exit 1
        fi
        sleep 5
    done
fi

execution="$(az rest --method post --url "$job_url/start?$api" --output json |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])')"
echo "Started $job ($execution)"

# Print the execution's log lines that are newer than the last one printed.
last_seen=""
print_new_logs() {
    last_seen="$(python3 - "$workspace" "$execution" "$last_seen" <<'PY'
import json, subprocess, sys
workspace, execution, last_seen = sys.argv[1:4]
query = (
    "ContainerAppConsoleLogs_CL"
    f" | where ContainerGroupName_s startswith '{execution}'"
    + (f" | where TimeGenerated > datetime({last_seen})" if last_seen else "")
    + " | order by TimeGenerated asc | project TimeGenerated, Log_s"
)
result = subprocess.run(
    ["az", "rest", "--method", "post", "--resource", "https://api.loganalytics.io",
     "--url", f"https://api.loganalytics.io/v1/workspaces/{workspace}/query",
     "--body", json.dumps({"query": query})],
    check=True, capture_output=True, text=True,
)
rows = json.loads(result.stdout)["tables"][0]["rows"]
for _, line in rows:
    print(line.rstrip(), file=sys.stderr)
print(rows[-1][0] if rows else last_seen)
PY
)"
}

status=""
while :; do
    status="$(az rest --method get --url "$job_url/executions/$execution?$api" --output json |
        python3 -c 'import json, sys; print(json.load(sys.stdin)["properties"]["status"])')"
    print_new_logs
    case "$status" in
        Succeeded | Failed | Stopped | Degraded) break ;;
    esac
    sleep 20
done

# Wait for the last log lines to reach Log Analytics.
for _ in 1 2 3 4 5 6 7 8 9; do
    sleep 20
    print_new_logs
done

if [ "$status" != Succeeded ]; then
    echo "$job ($execution) ended with status $status." >&2
    exit 1
fi
echo "$job ($execution) succeeded."
