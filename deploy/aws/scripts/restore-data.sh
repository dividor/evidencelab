#!/usr/bin/env bash
# Load another deployment's data into this AWS deployment from the transfer
# bucket: a Postgres export and an archive of one data source's folder, or a
# whole dump made by dump-data.sh, search index included.
#
# Usage:
#   deploy/aws/scripts/restore-data.sh inspect <postgres-key>
#   deploy/aws/scripts/restore-data.sh restore <postgres-key> <data-key> <data-source> [--yes]
#   deploy/aws/scripts/restore-data.sh load-dump <manifest-key> [--yes]
#   SOURCE_PROFILE=<profile> deploy/aws/scripts/restore-data.sh copy-dump <source-bucket> <manifest-key>
#
# Upload the files first; their keys are their names in the bucket:
#   bucket="$(terraform -chdir=deploy/aws output -raw transfer_bucket)"
#   aws s3 cp postgres-evidencelab-2026-11-20.sql.gz "s3://$bucket/"
#   aws s3 cp reports-data-2026-11-20.tar.gz "s3://$bucket/"
# A dump keeps the keys it was written under, such as
#   dumps/20261121T043910Z/manifest.json and the files it lists.
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
# load-dump, after you confirm (restore task,
# scripts/sync/db/load_dump_from_s3.py, except step 3):
#   1. checks every file in the dump against its manifest;
#   2. loads the export and the archive, as restore's step 1 does;
#   3. runs the database migrations (migrate task);
#   4. replaces the data source's Qdrant collections with the dump's
#      snapshots. The search index comes with the dump, so nothing is marked
#      for indexing.
#
# copy-dump brings a dump in from another deployment's transfer bucket, such
# as a checked test site's, under the same keys, ready for load-dump. Your
# machine only signs a download link for each file with SOURCE_PROFILE, the
# other account's AWS profile; a link lasts as long as that sign-in does, at
# most an hour. The restore task downloads each file inside AWS, checks its
# size and SHA-256 against the manifest, and only then stores it
# (load_dump_from_s3.py fetch). The file of links is deleted afterwards.
#
# Needs terraform and the aws CLI. Set AWS_PROFILE to pick the AWS account.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
tf="${TERRAFORM:-terraform}"
run_task="$here/scripts/run-task.sh"
load_dump="scripts/sync/db/load_dump_from_s3.py"

usage() {
    echo "usage: restore-data.sh inspect <postgres-key>" >&2
    echo "       restore-data.sh restore <postgres-key> <data-key> <data-source> [--yes]" >&2
    echo "       restore-data.sh load-dump <manifest-key> [--yes]" >&2
    echo "       SOURCE_PROFILE=<profile> restore-data.sh copy-dump <source-bucket> <manifest-key>" >&2
    exit 2
}

links_key=""
work=""

# Delete the signed links, here and in the bucket, however copy_dump ends.
remove_links() {
    [ -n "$work" ] && rm -rf "$work"
    if [ -n "$links_key" ] && ! aws s3 rm "s3://$bucket/$links_key" --only-show-errors; then
        echo "Delete s3://$bucket/$links_key by hand: it holds signed links" >&2
    fi
}

# Sign a link to each file of the dump in SOURCE_BUCKET, put them in this
# deployment's bucket, and have the restore task copy the dump in.
copy_dump() {
    local source_bucket="$1" manifest_key="$2"
    trap remove_links EXIT
    links_key="$(dirname "$manifest_key")/links.json"
    work="$(mktemp -d)"
    AWS_PROFILE="$SOURCE_PROFILE" aws s3 cp "s3://$source_bucket/$manifest_key" \
        "$work/manifest.json" --only-show-errors
    python3 -c 'import json, sys; print("\n".join(f["key"] for f in json.load(open(sys.argv[1]))["files"]))' \
        "$work/manifest.json" > "$work/keys"
    while read -r key; do
        printf '%s\t%s\n' "$key" "$(AWS_PROFILE="$SOURCE_PROFILE" aws s3 presign \
            "s3://$source_bucket/$key" --expires-in 3600)"
    done < "$work/keys" > "$work/links.tsv"
    python3 - "$work/manifest.json" "$work/links.tsv" > "$work/links.json" <<'EOF_PY'
import json, sys
links = dict(line.rstrip("\n").split("\t", 1) for line in open(sys.argv[2]))
print(json.dumps({"manifest": json.load(open(sys.argv[1])), "links": links}))
EOF_PY
    aws s3 cp "$work/links.json" "s3://$bucket/$links_key" --only-show-errors
    "$run_task" restore python "$load_dump" fetch --links "$links_key"
}

# Ask the operator to type the database's name; stop unless they do.
confirm() {
    read -r -p "Type the database name to go ahead: " answer
    if [ "$answer" != "$database" ]; then
        echo "Nothing changed." >&2
        exit 1
    fi
}

case "${1:-}" in
    inspect)
        [ "$#" -eq 2 ] || usage
        exec "$run_task" restore python scripts/sync/db/restore_from_s3.py inspect --postgres-key "$2"
        ;;
    restore)
        { [ "$#" -eq 4 ] || { [ "$#" -eq 5 ] && [ "$5" = --yes ]; }; } || usage
        ;;
    load-dump)
        { [ "$#" -eq 2 ] || { [ "$#" -eq 3 ] && [ "$3" = --yes ]; }; } || usage
        ;;
    copy-dump)
        [ "$#" -eq 3 ] || usage
        if [ -z "${SOURCE_PROFILE:-}" ]; then
            echo "Set SOURCE_PROFILE to the AWS profile of the account the dump is in." >&2
            exit 2
        fi
        ;;
    *) usage ;;
esac

database="$($tf -chdir="$here" output -raw database_name)"
bucket="$($tf -chdir="$here" output -raw transfer_bucket)"

if [ "$1" = copy-dump ]; then
    echo "==> Copying s3://$2/$(dirname "$3")/ into s3://$bucket/ (restore task)"
    copy_dump "$2" "$3"
    exit 0
fi

if [ "$1" = load-dump ]; then
    manifest="$2"
    if [ "${3:-}" != --yes ]; then
        echo "This replaces the deployment's database '$database', the data source's folder"
        echo "on the file share and its search index with the dump s3://$bucket/$manifest."
        echo "The current database is kept, renamed and closed to connections."
        confirm
    fi
    echo "==> 1/4 Checking every file against the manifest (restore task)"
    "$run_task" restore python "$load_dump" check --manifest "$manifest"
    echo "==> 2/4 Loading the export and the data archive (restore task)"
    "$run_task" restore python "$load_dump" restore --manifest "$manifest" --database "$database"
    echo "==> 3/4 Running the database migrations (migrate task)"
    "$run_task" migrate
    echo "==> 4/4 Loading the search index from the Qdrant snapshots (restore task)"
    "$run_task" restore python "$load_dump" snapshots --manifest "$manifest"
    exit 0
fi

postgres_key="$2"
data_key="$3"
data_source="$4"

if [ "${5:-}" != --yes ]; then
    echo "This replaces the deployment's database '$database' with s3://$bucket/$postgres_key,"
    echo "unpacks s3://$bucket/$data_key into the file share, and empties the search index"
    echo "of '$data_source'. The current database is kept, renamed and closed to connections."
    confirm
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
