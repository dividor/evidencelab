# Environment Synchronization Scripts

This directory contains tools to synchronize data (Database and Files) between
your local environment and remote environments (Production/Azure).

## Directory Structure

- `db/`: Scripts for Qdrant + Postgres database synchronization.
- `files/`: Scripts for Azure File Share synchronization.

---

## 1. Azure-Mediated Qdrant Sync (Recommended for Large DBs)

If direct sync fails due to timeouts or network interruptions (common with large
>100MB snapshots), use the Azure File Share as an intermediary.

### Prerequisites (Azure)

- `az` CLI installed
- `azcopy` installed
- Logged in with `az login`

### Step 1: Backup to Azure (Run locally in Docker)

```bash
docker compose exec api python scripts/sync/db/sync_backup_to_remote.py --data-source <name>
```

For SCP:

```bash
docker compose exec api python scripts/sync/db/sync_backup_to_remote.py \
  --data-source <name> \
  --mode scp \
  --scp-host user@hostname \
  --scp-ssh-key id_rsa \
  --scp-remote-dir /remote/path
```

For SCP via IAP/SSH config (uses a Host entry in `~/.ssh/config`):

```bash
docker compose exec api python scripts/sync/db/sync_backup_to_remote.py \
  --data-source <name> \
  --mode scp_iap \
  --scp-host wfp-evidencelab-vm \
  --scp-remote-dir /remote/path \
  --scp-ssh-config ~/.ssh/config
```

For Google Cloud Storage:

```bash
docker compose exec api python scripts/sync/db/sync_backup_to_remote.py \
  --data-source <name> \
  --mode gcp_storage \
  --gcp-bucket your-bucket-name \
  --gcp-prefix db/backups
```

To download the uploaded backup from GCS (before restoring):

```bash
gsutil -m cp gs://your-bucket-name/db/backups/qdrant_dump_<data_source>_<timestamp>.zip /tmp/
```

Then restore from the zip:

```bash
python scripts/sync/db/deploy_backup_to_db.py --source /tmp/qdrant_dump_<data_source>_<timestamp>.zip
```

* Dumps local Qdrant collections.
* Zips the dump directory.
* Uploads the `.zip` to Azure File Share (`db/backups/`).

### Step 2: Restore from Azure (Run on target machine)

```bash
python scripts/sync/db/deploy_backup_to_db.py
```

Note: `deploy_backup_to_db.py` orchestrates `docker compose` and must run on a host
with Docker access (not inside a container).

* Downloads the latest `.zip` backup from Azure.
* Restores all snapshots contained in the zip to the local Qdrant instance.

---

## 2. Azure-Mediated Postgres Sync

These commands run on a host with Docker access.

### Backup to Azure

```bash
python scripts/sync/db/sync_backup_to_remote.py \
  --db postgres \
  --db-name <db_name>
```

### Restore from Azure (manual unzip)

```bash
# Download the zip from your remote store (Azure/GCS/SCP)
unzip postgres_dump_<db_name>_<timestamp>.zip -d /tmp/postgres_dump

# Restore into Postgres
python scripts/sync/db/restore_postgres.py \
  --source /tmp/postgres_dump/postgres_dump_<db_name>_<timestamp>
```

---

## 3. Qdrant Full Dump/Load (Local or Remote)

These scripts handle full snapshots for a single data source.

### Prerequisites

- **Local Qdrant**: Must be running (`docker compose up -d`).
- **Volume Mount**: Your `docker-compose.yml` must mount `./db/backups` to `/qdrant/snapshots`.
- **Environment Variables**: `.env` must contain `QDRANT_HOST` and `QDRANT_API_KEY` for the **Remote** environment.

### Full Dump

```bash
docker compose exec api python scripts/sync/db/dump_qdrant.py --output db/backups --data-source <name>
```

* Produces a `qdrant_dump_<data_source>_<timestamp>/` directory with `.snapshot` files.

### Full Restore

```bash
python scripts/sync/db/deploy_backup_to_db.py --source db/backups/qdrant_dump_<data_source>_<timestamp>
```

* Restores snapshots by unpacking directly into the Qdrant storage volume.

---

## 3. Qdrant Delta Dump/Load

Use binary deltas for large collections to avoid shipping full snapshots every time.
These scripts require `xdelta3` to be available in the container or environment
that runs them.

### Delta Dump (creates `qdrant_delta_*`)

Use the main sync script with `--delta`:

```bash
docker compose exec api python scripts/sync/db/sync_backup_to_remote.py \
  --data-source <name> \
  --delta
```

### Delta Apply (reconstruct snapshots)

Restore directly from a delta backup:

```bash
python scripts/sync/db/deploy_backup_to_db.py \
  --source db/backups/qdrant_delta_<data_source>_<timestamp> \
  --delta
```

## 4. Postgres Full Dump/Restore (Local)

These commands run on a host with Docker access.

### Full Dump

Run from the host, using Docker for Postgres access:

```bash
python scripts/sync/db/dump_postgres.py
```

Defaults come from `.env`:
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

Use production compose if needed:

```bash
python scripts/sync/db/dump_postgres.py --prod
```

Override any value if needed:

```bash
python scripts/sync/db/dump_postgres.py \
  --db-name <db_name> \
  --db-user <db_user> \
  --db-password <db_password>
```

### Full Restore

```bash
python scripts/sync/db/restore_postgres.py \
  --source db/backups/postgres_dump_<db_name>_<timestamp> \
  --clean
```

---

## 5. File Synchronization (Azure)

These scripts sync large files (PDFs, images) stored in Azure File Shares.

### Prerequisites

- **Environment Variables**: `.env` must contain:
  - `STORAGE_ACCOUNT_NAME`
  - `STORAGE_ACCOUNT_KEY`
  - `STORAGE_SHARE_NAME`

## 6. Remote Upload Modes (SCP / GCP)

### Prerequisites (SCP)

- `scp` installed
- SSH key available and authorized on the remote host
- For IAP tunnels, a valid SSH config entry (e.g., `~/.ssh/config`)

### Prerequisites (GCP Storage)

- Google Cloud SDK (`gcloud`) installed
- Authenticated:
  - `gcloud auth login`
  - `gcloud auth application-default login`
  - Set project: `gcloud config set project <project-id>`
  - Verify access: `gcloud storage ls gs://your-bucket-name`

Install Google Cloud SDK (includes `gcloud storage` and `gsutil`):

```bash
# macOS (Homebrew)
brew install --cask google-cloud-sdk
gcloud init

# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates gnupg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] http://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo tee /usr/share/keyrings/cloud.google.gpg >/dev/null
sudo apt-get update && sudo apt-get install -y google-cloud-sdk
```

### Scripts

#### `files/sync_azure.py`

**Goal**: Sync files between Azure and your local `~/mnt/azure/<share_name>` folder.

**Download (Azure -> Local)**

```bash
python scripts/sync/files/sync_azure.py --download
```

*Note: Excludes `cache` directory automatically.*

**Upload (Local -> Azure)**

```bash
python scripts/sync/files/sync_azure.py --upload
```

### AzCopy (High Performance)

For faster transfers, you can use the `--azcopy` flag. This requires `azcopy` to be installed.

**Installation (macOS)**

```bash
brew install azcopy
```

**Usage**

```bash
python scripts/sync/files/sync_azure.py --upload --dirs uneg,worldbank --azcopy
```
