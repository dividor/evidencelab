# Deploying to the Cloud

Evidence Lab runs as a set of containers. On a single machine, Docker Compose runs all of them, including the databases (see [Running from the Published Image](docker-images.md)). A production deployment on a cloud's managed container service — Amazon ECS, Azure Container Apps or Google Cloud Run — runs the same images, with a few differences:

- each service can run several copies behind a load balancer;
- the databases and file storage are the cloud's managed services instead of containers;
- a few settings tell the containers where everything is.

This page describes that layout and the settings it needs. Each cloud has an example deployment page saying exactly what it deploys:

- [Example Deployment: AWS](cloud-aws.md): Amazon ECS on Fargate, RDS for PostgreSQL, ElastiCache and EFS
- [Example Deployment: Azure](cloud-azure.md): Azure Container Apps, Azure Database for PostgreSQL, Azure Managed Redis and Azure Files
- [Example Deployment: Google Cloud](cloud-gcp.md): Cloud Run, Cloud SQL for PostgreSQL, Memorystore and Filestore

All three use Qdrant Cloud in the same cloud and region.

![What runs where in a cloud deployment](../images/admin/cloud-deployment.png)

## What runs where

| Part | Runs as | Notes |
|---|---|---|
| Load balancer | The cloud's load balancer | The only public entry point. Ends HTTPS with a managed certificate and sends all traffic to the ui service. |
| ui | Container service, 2 or more copies | The production web app image (`ui/frontend/Dockerfile.prod`). nginx serves the web app and forwards `/api` to the api, and `/mcp` and `/a2a` to the mcp service. Build it for each deployment, because the build fixes the sign-in mode, data sources and branding into the page. |
| api | Container service, 2 or more copies | The published `astrobagel/evidencelab` image. |
| mcp | Container service, 2 or more copies | The same image, started with `python -m mcp_server.http_server`. |
| embedding | Container service, 1 copy, always running | The `michaelf34/infinity` image. Keep at least one copy running: loading the model takes several minutes. |
| migrate | A job, run before each release starts | The same image, running `alembic upgrade head`. |
| pipeline | A job, run when you ingest documents | The same image, running the pipeline orchestrator. |
| Postgres 16 with pgvector | The cloud's managed Postgres | Backups, a standby copy and patching come with the service. |
| Qdrant | Qdrant Cloud, in the same cloud and region | Or a small virtual machine running Qdrant. |
| Redis | The cloud's managed Redis | Holds the rate-limit counts that all api and mcp copies share. |
| Documents and page images | The cloud's network file share | Mounted at `/app/data` in the api and pipeline. The pipeline writes the files and the api serves them. |

Sizes in the figure come from the memory limits in `docker-compose.prod.yml`.

## Why the databases are managed services

Managed container services don't give a long-running service a disk that survives a redeploy or a restart. On Amazon ECS, a block-storage volume attached to a service's containers is deleted when the container stops. Azure Container Apps and Google Cloud Run offer only network file shares and memory. Qdrant's installation guide requires block storage and says it does not work on network file systems. So Postgres runs on the cloud's managed Postgres, and Qdrant on Qdrant Cloud or its own virtual machine.

## Settings

Docker Compose needs none of these settings: the defaults match it. A cloud deployment sets them on the containers listed.

### Where the ui finds the other services

The ui container fills these into its nginx configuration when it starts. If a value is not valid, the container stops with an error instead of starting with a broken configuration.

| Setting | Set on | Default | Set it to |
|---|---|---|---|
| `API_UPSTREAM` | ui | `http://api:8000` | The address of the api service, for example `http://api.evidencelab.internal:8000` |
| `MCP_UPSTREAM` | ui | `http://mcp:8001` | The address of the mcp service |
| `NGINX_RESOLVER` | ui | `127.0.0.11` (Docker's DNS server) | The DNS server of the cloud network, which nginx uses to look up the mcp service |
| `NGINX_REAL_IP_FROM` | ui | `127.0.0.1` (no proxy trusted) | The address range of the load balancer, for example the network's range `10.0.0.0/16` |

### Visitors' real addresses

Rate limits count requests per visitor address. Behind a load balancer and nginx, every request reaches the api from nginx's address, so without these settings all visitors share one count.

- `NGINX_REAL_IP_FROM` on the ui makes nginx take the visitor's address from the `X-Forwarded-For` header the load balancer adds. Only proxies in that range are believed, so a visitor cannot fake their address. The mcp server rate-limits on the address nginx passes on.
- `FORWARDED_ALLOW_IPS` on the api lists the addresses of nginx (the ui copies), for example the network's range `10.0.0.0/16`. The api then takes the visitor's address from the header nginx sends. Without it, the api only trusts its own machine (`127.0.0.1`).

### Rate limits shared by all copies

| Setting | Set on | Value |
|---|---|---|
| `RATELIMIT_STORAGE_URL` | api, mcp | `redis://<redis-host>:6379/0` (or `rediss://` for Redis over TLS) |

Without it, each copy keeps its own counts, so with two copies a visitor gets twice the configured limit. The sign-in attempt limit (`AUTH_RATE_LIMIT_MAX`) is always counted by each copy separately.

### Postgres over verified TLS

| Setting | Set on | Value |
|---|---|---|
| `PGSSLMODE` | api, mcp, pipeline, migrate | `verify-full` |
| `PGSSLROOTCERT` | api, mcp, pipeline, migrate | Path to the cloud provider's certificate authority bundle inside the container |

These are the standard Postgres client settings, read by every Postgres connection Evidence Lab makes. With `verify-full`, a connection is refused unless the server's certificate is signed by that authority and matches the `POSTGRES_HOST` name. Without these settings, connections to a server that supports TLS are encrypted but the server's certificate is not checked.

### Starting the api

Give the api copies a start command without the migration step:

```bash
uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Run the migrate job with `alembic upgrade head` before the new api copies start. Several copies each migrating on start-up, as the single-machine compose files do, would run the same migration at the same time.

## Not included

- **Reprocessing from the admin screens.** The reprocess actions queue background tasks for a Celery worker, which this layout does not run.
- **Large ingestions.** Processing many documents needs far more memory than serving them. Run the pipeline job with enough memory, or run large ingestions elsewhere and copy the results in (see [Database Maintenance](database-maintenance.md)).
