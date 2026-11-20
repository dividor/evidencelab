#!/usr/bin/env bash
# Load another deployment's data into this AWS deployment: a Postgres export
# and an archive of one data source's folder, uploaded to the transfer bucket.
#
# Usage:
#   deploy/aws/scripts/restore-data.sh inspect <postgres-key>
#   deploy/aws/scripts/restore-data.sh restore <postgres-key> <data-key> <data-source> [--yes]
#
# Upload the two files first; their keys are their names in the bucket:
#   bucket="$(terraform -chdir=deploy/aws output -raw transfer_bucket)"
#   aws s3 cp postgres-evidencelab-2026-11-20.sql.gz "s3://$bucket/"
#   aws s3 cp wfp-data-2026-11-20.tar.gz "s3://$bucket/"
#
# inspect prints what the export holds and changes nothing.
#
# restore, after you confirm:
#   1. unpacks the archive into the file share, then loads the export into a
#      new database and swaps it in for the running one, which is kept,
#      renamed, closed to connections (restore task,
#      scripts/sync/db/restore_from_s3.py);
#   2. runs the database migrations (migrate task);
#   3. empties the data source's search index and marks its documents for
#      indexing (pipeline task, scripts/pipeline/prepare_reindex.py);
# and prints the pipeline command that rebuilds the search index.
#
# Needs terraform and the aws CLI. Set AWS_PROFILE to pick the AWS account.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
tf="${TERRAFORM:-terraform}"
run_task="$here/scripts/run-task.sh"

usage() {
    echo "usage: restore-data.sh inspect <postgres-key>" >&2
    echo "       restore-data.sh restore <postgres-key> <data-key> <data-source> [--yes]" >&2
    exit 2
}

case "${1:-}" in
    inspect)
        [ "$#" -eq 2 ] || usage
        exec "$run_task" restore python scripts/sync/db/restore_from_s3.py inspect --postgres-key "$2"
        ;;
    restore)
        { [ "$#" -eq 4 ] || { [ "$#" -eq 5 ] && [ "$5" = --yes ]; }; } || usage
        ;;
    *) usage ;;
esac

postgres_key="$2"
data_key="$3"
data_source="$4"
database="$($tf -chdir="$here" output -raw database_name)"
bucket="$($tf -chdir="$here" output -raw transfer_bucket)"

if [ "${5:-}" != --yes ]; then
    echo "This replaces the deployment's database '$database' with s3://$bucket/$postgres_key,"
    echo "unpacks s3://$bucket/$data_key into the file share, and empties the search index"
    echo "of '$data_source'. The current database is kept, renamed and closed to connections."
    read -r -p "Type the database name to go ahead: " answer
    if [ "$answer" != "$database" ]; then
        echo "Nothing changed." >&2
        exit 1
    fi
fi

echo "==> 1/3 Loading the export and the data archive (restore task)"
"$run_task" restore python scripts/sync/db/restore_from_s3.py restore \
    --postgres-key "$postgres_key" --data-key "$data_key" \
    --data-source "$data_source" --database "$database"

echo "==> 2/3 Running the database migrations (migrate task)"
"$run_task" migrate

echo "==> 3/3 Emptying the search index and marking documents for indexing (pipeline task)"
"$run_task" pipeline python scripts/pipeline/prepare_reindex.py --data-source "$data_source"

echo
echo "Next, rebuild the search index. Try five documents first:"
echo "  deploy/aws/scripts/run-task.sh pipeline python -m pipeline.orchestrator --data-source $data_source \\"
echo "    --skip-download --skip-scan --skip-parse --skip-summarize --skip-tag --num-records 5"
echo "then run it again without --num-records (and with --workers N) for the rest."
