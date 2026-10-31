## Running from the Published Image

Every Evidence Lab release publishes a ready-built `evidencelab` image. It holds the API, the MCP server and the document pipeline, which is the part that takes longest to build. One image runs all three, each with a different start command.

The image is on Docker Hub as [`astrobagel/evidencelab`](https://hub.docker.com/r/astrobagel/evidencelab). The same image is mirrored to the GitHub Container Registry as `ghcr.io/dividor/evidencelab`.

It is built for `linux/amd64` and `linux/arm64`, so it runs on Intel and AMD servers and on Apple Silicon Macs.

The web interface is not published as an image. Building it fixes three things into the page your browser loads: the API key or sign-in mode, the data sources from `config.json`, and your branding. A shared image would either fail to reach your API or give away a key. The compose file below builds it on your machine instead, which takes about three minutes.

The database, vector store and embedding model use their own upstream images: PostgreSQL with pgvector, Qdrant and Infinity.

### Tags

| Tag | Meaning |
|---|---|
| `1.6.5` | An exact release. Use this in production. |
| `1.6` | The newest patch of a minor release. |
| `latest` | The newest release. |
| `rc-v1.6.6` | The release candidate in progress. It changes as work is merged and is for testing only. |

Images are published from v1.6.5 onward. Earlier releases have no published image; build them from source with `docker-compose.prod.yml`.

### Quick start

You need Docker with Compose, Python 3 (no extra packages), git, and about 25 GB of free disk for the images and the embedding model. You also need an API key for one model provider: Azure Foundry, Hugging Face (a free token works) or Google Vertex.

```bash
git clone https://github.com/dividor/evidencelab.git
cd evidencelab
python3 scripts/demo/run_demo.py --mode hub
```

The script asks which model provider to use and for its key, then does everything else:

1. Writes `.env`, generating the passwords and secret keys. On a later run it keeps the ones already there.
2. Adds a **Demo Data from World Bank** data source to `config.json`.
3. Downloads three World Bank reports and runs the pipeline on them, inside the published image.
4. Builds the web interface and starts Evidence Lab.

When it finishes, open http://localhost:8080 and choose the demo data source.

Options:

- `--version 1.6.5` picks the image tag. The default is `EVIDENCELAB_VERSION` from `.env`, else `latest`. Check out the matching tag, `git checkout v1.6.5`, so the compose file and web interface match the image.
- `--num-docs 10` loads more documents.
- `--skip-download` or `--skip-pipeline` re-runs only part of it.

The script saves the image tag in `.env`, so afterwards plain commands work:

```bash
docker compose -f docker-compose.hub.yml down     # stop
docker compose -f docker-compose.hub.yml up -d    # start again
```

### Manual setup

To set it up without the script, copy the example settings and fill them in:

```bash
cp .env.example .env
```

Set at least these values:

- `EVIDENCELAB_VERSION`: the image tag, for example `1.6.5`.
- `POSTGRES_PASSWORD`: any strong password.
- `API_SECRET_KEY`: a random string, for example from `openssl rand -hex 32`. The API will not start without it.
- `AUTH_SECRET_KEY`: a different random string of 32 or more characters.
- `REACT_APP_API_KEY`: see [How the web interface reaches the API](#how-the-web-interface-reaches-the-api). The compose file stops if it is missing.
- The keys for the language model provider your `config.json` uses. The stock `config.json` uses Azure Foundry, which needs `AZURE_FOUNDRY_KEY` and `AZURE_FOUNDRY_ENDPOINT`. See [Optional Third-Party Services](third-party-services.md).

Then start Evidence Lab and open http://localhost:8080:

```bash
docker compose -f docker-compose.hub.yml up -d
```

The first start builds the web interface and downloads the embedding model, which takes a few minutes. The API waits for the database, vector store and embedding model, then applies any database migrations.

### How the web interface reaches the API

The API accepts a request only if it carries an API key or comes from a signed-in user.

- **Sign-in off (the default).** The browser sends `REACT_APP_API_KEY` with every request. Set it to the same value as `API_SECRET_KEY`. Anyone who can open the page can read this key, so use this only on your own machine or a private network.
- **Sign-in on.** Set `USER_MODULE` and `REACT_APP_USER_MODULE` to `on_passive` or `on_active`, and leave the key empty with `REACT_APP_API_KEY=`. Signed-in users reach the API with a session cookie, and no key is exposed. See [User Administration](user-administration.md).

Rebuild the web interface after changing either setting:

```bash
docker compose -f docker-compose.hub.yml build ui
EVIDENCELAB_VERSION=<version> docker compose -f docker-compose.hub.yml up -d
```

### Settings for the compose file

Set these in `.env` or on the command line.

| Variable | Default | Purpose |
|---|---|---|
| `EVIDENCELAB_VERSION` | none, required | The image tag to run. |
| `EVIDENCELAB_REGISTRY` | `docker.io/astrobagel` | Where to pull the image from. Set `ghcr.io/dividor` to use the GitHub mirror, for example if Docker Hub's pull limit for anonymous users gets in the way. |
| `EVIDENCELAB_PORT` | `8080` | The port the web interface listens on. |
| `EVIDENCELAB_BIND` | `127.0.0.1` | The address the web interface listens on. The default only accepts connections from the same machine. Put an HTTPS proxy in front, or set `0.0.0.0` to accept connections from other machines. |
| `EVIDENCELAB_CONFIG` | `config.json` in `CONFIG_SRC`, else `./config.json` | The configuration file the API, MCP server and pipeline read. Start-up fails if the file is missing. |
| `DATA_MOUNT_PATH` | `./data` | Source documents and parsed output. |
| `CACHE_MOUNT_PATH` | `./.cache` | Downloaded model files. |
| `APP_BASE_URL` and `CORS_ALLOWED_ORIGINS` | `http://localhost:8080` | Set both to the address users type into their browser. |
| `CUSTOMIZE_ASSETS` and `CONFIG_SRC` | `./customize` and `.` | Branding and `config.json` for the web interface build. See [Customization & Branding](customization.md). |

PostgreSQL and Qdrant keep their data in Docker named volumes (`evidencelab-hub_postgres-data`, `evidencelab-hub_qdrant-data` and `evidencelab-hub_qdrant-snapshots`), not in a folder, because Postgres on Docker Desktop for Mac can refuse a bind-mounted data folder. `docker compose -f docker-compose.hub.yml down` keeps them; adding `-v` deletes them. Keep the data folder on a disk with room for parsed output, because parsing expands a collection substantially.

### Adding documents

The pipeline uses the same `evidencelab` image. It starts only when you ask for it:

```bash
docker compose -f docker-compose.hub.yml --profile pipeline up -d pipeline
docker compose -f docker-compose.hub.yml exec pipeline \
  python -m pipeline.orchestrator --data-source <key> --skip-download --num-records 10
```

See [Getting Started](../overview/getting-started.md) for how to lay out documents and metadata, and [Pipeline Configuration](pipeline-configuration.md) for the options.

Containers cannot use Apple MPS acceleration, so parsing in Docker on a Mac is slow. The host runner described in [Pipeline Configuration](pipeline-configuration.md) is faster there.

If you add or rename data sources in `config.json`, restart the API and rebuild the web interface so both see the change.

### Upgrading

Check out the new version, then pull, rebuild and restart:

```bash
git checkout v<new version>
EVIDENCELAB_VERSION=<new version> docker compose -f docker-compose.hub.yml pull --ignore-buildable
EVIDENCELAB_VERSION=<new version> docker compose -f docker-compose.hub.yml up -d --build
```

The API applies database migrations when it starts. Take a backup first, as described in [Database Maintenance](database-maintenance.md).

### Checking an image

Each published image carries a record of how it was built (its build provenance) and a list of the software inside it (a software bill of materials). You can read both with Docker:

```bash
docker buildx imagetools inspect astrobagel/evidencelab:<version> \
  --format '{{ json .Provenance }}'
docker buildx imagetools inspect astrobagel/evidencelab:<version> \
  --format '{{ json .SBOM }}'
```
