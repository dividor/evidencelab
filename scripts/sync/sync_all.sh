echo "Syncing PDFS..."
python scripts/sync/files/sync_azure.py --upload --dirs "uneg/pdfs" --azcopy

echo "Syncing DB..."
docker compose exec pipeline python ./scripts/sync/db/sync_local_to_remote.py

echo "Syncing Parsed..."

echo "Saving DB dumps to repote file system..."
