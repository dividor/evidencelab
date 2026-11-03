#!/usr/bin/env bash
# Run the migrate or pipeline task once, wait for it to finish, show its log
# and exit with its exit code.
#
# Usage:
#   deploy/aws/scripts/run-task.sh migrate
#   deploy/aws/scripts/run-task.sh pipeline python -m pipeline.orchestrator --data-source <name>
#
# Words after the task name replace the task's command. Needs the aws CLI and
# terraform; set TERRAFORM to run terraform some other way and AWS_PROFILE to
# pick the AWS account.
set -euo pipefail

if [ "$#" -lt 1 ] || { [ "$1" != migrate ] && [ "$1" != pipeline ]; }; then
    echo "usage: run-task.sh migrate|pipeline [command ...]" >&2
    exit 2
fi
task="$1"
shift

here="$(cd "$(dirname "$0")/.." && pwd)"
tf="${TERRAFORM:-terraform}"
output() { $tf -chdir="$here" output -raw "$1"; }

region="$(output region)"
cluster="$(output cluster)"
family="$(output "${task}_task_definition")"
security_group="$(output tasks_security_group_id)"
subnets="$($tf -chdir="$here" output -json private_subnet_ids | python3 -c 'import json, sys; print(",".join(json.load(sys.stdin)))')"
log_group="$($tf -chdir="$here" output -json log_groups | python3 -c "import json, sys; print(json.load(sys.stdin)['$task'])")"

overrides="$(python3 - "$task" "$@" <<'EOF'
import json, sys
task, command = sys.argv[1], sys.argv[2:]
container = {"name": task}
if command:
    container["command"] = command
print(json.dumps({"containerOverrides": [container]}))
EOF
)"

task_arn="$(aws ecs run-task --region "$region" --cluster "$cluster" \
    --task-definition "$family" --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=DISABLED}" \
    --overrides "$overrides" \
    --query 'tasks[0].taskArn' --output text)"
task_id="${task_arn##*/}"
echo "Started $task task $task_id"

status=""
while [ "$status" != STOPPED ]; do
    sleep 15
    status="$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task_arn" \
        --query 'tasks[0].lastStatus' --output text)"
    echo "  $(date +%H:%M:%S) $status"
done

aws logs tail "$log_group" --region "$region" --log-stream-names "$task/$task/$task_id" --format short || true

read -r exit_code reason <<<"$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task_arn" \
    --query 'tasks[0].[containers[0].exitCode, stoppedReason]' --output text)"
echo "$task task finished: exit code $exit_code ($reason)"
if [ "$exit_code" != 0 ]; then
    exit 1
fi
