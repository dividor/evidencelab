#!/usr/bin/env bash
# Dump this AWS deployment's data to its transfer bucket, for a copy kept
# elsewhere or for loading into another deployment with restore-data.sh.
#
# Usage:
#   deploy/aws/scripts/dump-data.sh <data-source>
#
# Writes under dumps/<UTC time>/ in the transfer bucket (restore task,
# scripts/sync/db/dump_to_s3.py):
#   postgres-<database>-<time>.sql.gz   the database, as plain SQL
#   qdrant-<collection>-<time>.snapshot one per Qdrant collection of the source
#   <data-source>-<time>.tar            the data source's folder on the file share
#   manifest.json                       each file's size and SHA-256, and versions
# and prints the command that downloads them.
#
# The transfer bucket deletes its files after transfer_retention_days, and
# with the deployment: copy the dump somewhere lasting.
#
# Needs terraform and the aws CLI. Set AWS_PROFILE to pick the AWS account.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
tf="${TERRAFORM:-terraform}"

if [ "$#" -ne 1 ]; then
    echo "usage: dump-data.sh <data-source>" >&2
    exit 2
fi
data_source="$1"
database="$($tf -chdir="$here" output -raw database_name)"
bucket="$($tf -chdir="$here" output -raw transfer_bucket)"

"$here/scripts/run-task.sh" restore python scripts/sync/db/dump_to_s3.py dump \
    --data-source "$data_source" --database "$database"

echo
echo "Download the newest dump with:"
echo "  aws s3 ls s3://$bucket/dumps/"
echo "  aws s3 cp --recursive s3://$bucket/dumps/<time>/ <local folder>/"
