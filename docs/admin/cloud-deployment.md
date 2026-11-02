# Deploying to Cloud Platforms

Evidence Lab runs as a set of containers. On a single machine, Docker Compose runs all of them, including the databases (see [Running from the Published Image](docker-images.md)). A production deployment on a cloud's managed container service runs the same images, with a few differences:

- each service can run several copies behind a load balancer;
- the databases and file storage are the cloud's managed services instead of containers;
- a few settings tell the containers where everything is.

This page describes that layout, the settings it needs, and an example deployment on each of AWS, Azure and Google Cloud.

**On this page**

| Section | What it covers |
|---|---|
| [The cloud layout](#the-cloud-layout) | What runs where, on every cloud, and why the databases are managed services |
| [Settings](#settings) | The settings a load-balanced deployment needs |
| [Example: AWS](#example-aws) | Amazon ECS on Fargate, RDS for PostgreSQL, ElastiCache and EFS |
| [Example: Azure](#example-azure) | Azure Container Apps, Azure Database for PostgreSQL, Azure Managed Redis and Azure Files |
| [Example: Google Cloud](#example-google-cloud) | Cloud Run, Cloud SQL for PostgreSQL, Memorystore and Filestore |
| [Testing the examples](#testing-the-examples) | What each example's test deployment checks |
| [Not included](#not-included) | What this layout does not cover |

> **Status:** the three example deployments are being built. This page describes exactly what each one deploys. Each example's Terraform template, tested commands and measured running cost are added here once it has been deployed and tested end to end.

## The cloud layout

All three examples use the same layout. Only the names of the cloud services change, and all three use Qdrant Cloud in the same cloud and region.

![What runs where in a cloud deployment](../images/admin/cloud-deployment.png)

### What runs where

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

### Why the databases are managed services

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

## Example: AWS

This example runs Evidence Lab on Amazon ECS with Fargate, with Amazon RDS for Postgres, Qdrant Cloud, ElastiCache, EFS and an Application Load Balancer.

![What the AWS example deploys](../images/admin/cloud-aws.png)

### What the AWS example deploys

| Part | AWS service | Example size |
|---|---|---|
| Network | A VPC (`10.0.0.0/16`) across two availability zones. Public subnets hold the load balancer and a NAT gateway; private subnets hold everything else. | One NAT gateway, so the containers can pull images and reach the model providers and Qdrant Cloud |
| Load balancer | Application Load Balancer, HTTPS on port 443 with an ACM certificate, HTTP redirected to HTTPS | Idle timeout 300 seconds, for streaming chat and MCP connections |
| ui | ECS service on Fargate, your web app image from ECR | 2 tasks, 0.25 vCPU, 0.5 GB each |
| api | ECS service on Fargate, `astrobagel/evidencelab` | 2 tasks, 2 vCPU, 8 GB each |
| mcp | ECS service on Fargate, `astrobagel/evidencelab` | 2 tasks, 0.5 vCPU, 2 GB each |
| embedding | ECS service on Fargate, `michaelf34/infinity:0.0.70` | 1 task, 1 vCPU, 4 GB, always running |
| migrate | ECS task on Fargate, run before each release | 0.5 vCPU, 1 GB |
| pipeline | ECS task on Fargate, run when you ingest documents | 4 vCPU, 16 GB |
| Postgres | Amazon RDS for PostgreSQL 16, Multi-AZ, with the `vector` extension | db.t4g.medium, 50 GB gp3 storage, 7 days of automated backups |
| Qdrant | Qdrant Cloud cluster in the same AWS region | Sized from your collection |
| Redis | Amazon ElastiCache (Valkey, compatible with Redis), encrypted in transit | cache.t4g.micro |
| Documents and page images | Amazon EFS, mounted at `/app/data` in the api and pipeline | Elastic throughput |
| Web app image | Amazon ECR repository | — |
| Keys and passwords | AWS Secrets Manager | — |
| Logs | Amazon CloudWatch Logs, one log group per service | 30 days |
| Domain | An Amazon Route 53 record pointing at the load balancer | — |

All resources are tagged with the deployment name, so you can find them later.

### How the AWS services find each other

The api, mcp and embedding services register in an AWS Cloud Map private DNS namespace, `evidencelab.internal`. These are the values the example sets, using the settings described in [Settings](#settings):

| Container | Setting | Value |
|---|---|---|
| ui | `API_UPSTREAM` | `http://api.evidencelab.internal:8000` |
| ui | `MCP_UPSTREAM` | `http://mcp.evidencelab.internal:8001` |
| ui | `NGINX_RESOLVER` | `10.0.0.2`, the VPC's DNS server |
| ui | `NGINX_REAL_IP_FROM` | `10.0.0.0/16` |
| api | `FORWARDED_ALLOW_IPS` | `10.0.0.0/16` |
| api, mcp | `RATELIMIT_STORAGE_URL` | `rediss://<ElastiCache endpoint>:6379/0` |
| api, mcp, pipeline, migrate | `POSTGRES_HOST` | The RDS endpoint |
| api, mcp, pipeline, migrate | `PGSSLMODE`, `PGSSLROOTCERT` | `verify-full`, and the RDS certificate bundle |
| api, mcp, pipeline | `QDRANT_HOST`, `QDRANT_API_KEY` | Your Qdrant Cloud cluster's URL and key |
| api, pipeline | `EMBEDDING_API_URL` | `http://embedding.evidencelab.internal:7997` |

The api starts with `uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --workers 1`, without the migration step. The migrate task runs `alembic upgrade head` first.

### Deploying the AWS example

**You need:**
- an AWS account, and the AWS CLI signed in to it;
- Terraform and Docker on your machine;
- a domain you can point at the load balancer;
- a Qdrant Cloud cluster in your AWS region, with its URL and API key;
- your model provider keys, and your `config.json`.

**The steps:**
1. Copy the example settings file and fill in the region, domain, sizes, Evidence Lab version and the names of your keys.
2. Run Terraform to create the network, databases, file share, registry, load balancer and services.
3. Build the web app image with your settings and push it to ECR.
4. Run the migrate task and wait for it to finish.
5. The services start and pass their health checks. Open your domain.
6. Run the pipeline task to ingest your documents.

**Upgrading:** set the new Evidence Lab version, rebuild the web app image, run the migrate task, then let ECS replace the tasks one at a time.

**Removing the example:** `terraform destroy` removes everything it created. The Qdrant Cloud cluster is removed in Qdrant's console.

## Example: Azure

This example runs Evidence Lab on Azure Container Apps, with Azure Database for PostgreSQL, Qdrant Cloud, Azure Managed Redis and Azure Files.

![What the Azure example deploys](../images/admin/cloud-azure.png)

### What the Azure example deploys

| Part | Azure service | Example size |
|---|---|---|
| Network | A resource group and a virtual network, with subnets for the Container Apps environment, Postgres and private endpoints | — |
| Load balancer | The Container Apps environment's ingress, HTTPS with a free managed certificate for your domain | Only the ui app is reachable from the internet |
| Container platform | A Container Apps environment of the workload-profiles type, using the Consumption profile | Needed for the 4 vCPU, 8 GB size the api uses |
| ui | Container app, your web app image from Azure Container Registry | 2 replicas, 0.25 vCPU, 0.5 GB each |
| api | Container app, `astrobagel/evidencelab` | 2 replicas, 4 vCPU, 8 GB each (the Consumption profile's largest size) |
| mcp | Container app, `astrobagel/evidencelab` | 2 replicas, 1 vCPU, 2 GB each |
| embedding | Container app, `michaelf34/infinity:0.0.70` | 1 replica, 2 vCPU, 4 GB, never scaled to zero |
| migrate | Container Apps job, run before each release | 0.5 vCPU, 1 GB |
| pipeline | Container Apps job, run when you ingest documents | 4 vCPU, 8 GB |
| Postgres | Azure Database for PostgreSQL flexible server 16, zone-redundant high availability, with `vector` allowed in the `azure.extensions` server setting | General Purpose, 2 vCores, 128 GB storage, 7 days of backups |
| Qdrant | Qdrant Cloud cluster in the same Azure region | Sized from your collection |
| Redis | Azure Managed Redis | The smallest size |
| Documents and page images | An Azure Files share, mounted at `/app/data` in the api and pipeline | Sized from your data |
| Web app image | Azure Container Registry | — |
| Keys and passwords | Azure Key Vault | — |
| Logs | A Log Analytics workspace | 30 days |
| Domain | An Azure DNS record for your domain | — |

The example uses Azure Managed Redis because Microsoft no longer lets you create new Azure Cache for Redis instances.

The pipeline job runs the same way as the existing scripts in `scripts/pipeline/azure/container-apps/`. Processing large batches needs more than the Consumption profile's 8 GB; add a dedicated workload profile for that, or ingest elsewhere and copy the results in.

### How the Azure services find each other

The api, mcp and embedding apps use internal ingress, so only apps inside the environment can reach them. These are the values the example sets, using the settings described in [Settings](#settings):

| Container | Setting | Value |
|---|---|---|
| ui | `API_UPSTREAM` | `http://api.internal.<environment domain>` |
| ui | `MCP_UPSTREAM` | `http://mcp.internal.<environment domain>` |
| ui | `NGINX_RESOLVER` | `168.63.129.16`, Azure's DNS server |
| ui | `NGINX_REAL_IP_FROM` | The Container Apps subnet's range |
| api | `FORWARDED_ALLOW_IPS` | The Container Apps subnet's range |
| api, mcp | `RATELIMIT_STORAGE_URL` | `rediss://<Azure Managed Redis host>:10000/0` |
| api, mcp, pipeline, migrate | `POSTGRES_HOST` | The flexible server's name |
| api, mcp, pipeline, migrate | `PGSSLMODE`, `PGSSLROOTCERT` | `verify-full`, and the certificate authorities Azure Database for PostgreSQL uses |
| api, mcp, pipeline | `QDRANT_HOST`, `QDRANT_API_KEY` | Your Qdrant Cloud cluster's URL and key |
| api, pipeline | `EMBEDDING_API_URL` | `http://embedding.internal.<environment domain>` |

The api starts with `uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --workers 1`, without the migration step. The migrate job runs `alembic upgrade head` first.

### Deploying the Azure example

**You need:**
- an Azure subscription, and the Azure CLI signed in to it;
- Terraform and Docker on your machine;
- a domain you can point at the environment;
- a Qdrant Cloud cluster in your Azure region, with its URL and API key;
- your model provider keys, and your `config.json`.

**The steps:**
1. Copy the example settings file and fill in the region, domain, sizes, Evidence Lab version and the names of your keys.
2. Run Terraform to create the network, databases, file share, registry, Key Vault and the Container Apps environment.
3. Build the web app image with your settings and push it to Azure Container Registry.
4. Start the migrate job and wait for it to succeed.
5. The apps start. Add your domain's DNS record, and the managed certificate is issued. Open your domain.
6. Start the pipeline job to ingest your documents.

**Upgrading:** set the new Evidence Lab version, rebuild the web app image, run the migrate job, then deploy new revisions of the apps.

**Removing the example:** `terraform destroy` removes the resource group and everything in it. The Qdrant Cloud cluster is removed in Qdrant's console.

## Example: Google Cloud

This example runs Evidence Lab on Cloud Run, with Cloud SQL for PostgreSQL, Qdrant Cloud, Memorystore and Filestore behind an external Application Load Balancer.

![What the Google Cloud example deploys](../images/admin/cloud-gcp.png)

### What the Google Cloud example deploys

| Part | Google Cloud service | Example size |
|---|---|---|
| Network | A VPC network. Cloud Run reaches it with Direct VPC egress; Cloud SQL, Memorystore and Filestore use private addresses in it. | — |
| Load balancer | Global external Application Load Balancer with a Google-managed certificate, sending traffic to the ui service | — |
| ui | Cloud Run service, your web app image from Artifact Registry. Accepts traffic only from the load balancer. | Minimum 2 instances, 1 vCPU, 512 MB |
| api | Cloud Run service, `astrobagel/evidencelab`. Internal traffic only. CPU stays allocated between requests, for streaming answers. | Minimum 2 instances, 2 vCPU, 8 GB |
| mcp | Cloud Run service, `astrobagel/evidencelab`. Internal traffic only. | Minimum 2 instances, 1 vCPU, 2 GB |
| embedding | Cloud Run service, `michaelf34/infinity:0.0.70`. Internal traffic only. | Minimum 1 instance, 2 vCPU, 4 GB |
| migrate | Cloud Run job, run before each release | 1 vCPU, 1 GB |
| pipeline | Cloud Run job, run when you ingest documents | 4 vCPU, 16 GB |
| Postgres | Cloud SQL for PostgreSQL 16, regional high availability, private address only, with the `vector` extension | 2 vCPU, 8 GB, 50 GB SSD, 7 days of backups |
| Qdrant | Qdrant Cloud cluster in the same Google Cloud region | Sized from your collection |
| Redis | Memorystore for Redis, encrypted in transit | Basic tier, 1 GB |
| Documents and page images | Filestore Basic HDD share, mounted at `/app/data` in the api and pipeline | 1 TB, the smallest Basic HDD size |
| Web app image | Artifact Registry | — |
| Keys and passwords | Secret Manager | — |
| Logs | Cloud Logging | 30 days |
| Domain | A Cloud DNS record pointing at the load balancer | — |

Minimum instances keep every service warm. The embedding model takes minutes to load, and the api keeps streaming connections open.

### How the Google Cloud services find each other

Cloud Run services have HTTPS addresses ending in `run.app`. The ui reaches the api and mcp services at those addresses through the VPC. These are the values the example sets, using the settings described in [Settings](#settings):

| Container | Setting | Value |
|---|---|---|
| ui | `API_UPSTREAM` | The api service's `https://...run.app` address |
| ui | `MCP_UPSTREAM` | The mcp service's `https://...run.app` address |
| ui | `NGINX_RESOLVER` | The DNS server Cloud Run provides |
| ui | `NGINX_REAL_IP_FROM` | The address ranges Google's load balancers connect from |
| api | `FORWARDED_ALLOW_IPS` | The address ranges requests from the ui arrive from |
| api, mcp | `RATELIMIT_STORAGE_URL` | `rediss://<Memorystore address>:6378/0` |
| api, mcp, pipeline, migrate | `POSTGRES_HOST` | The Cloud SQL private address |
| api, mcp, pipeline, migrate | `PGSSLMODE`, `PGSSLROOTCERT` | `verify-full`, and the Cloud SQL instance's server certificate authority |
| api, mcp, pipeline | `QDRANT_HOST`, `QDRANT_API_KEY` | Your Qdrant Cloud cluster's URL and key |
| api, pipeline | `EMBEDDING_API_URL` | The embedding service's `https://...run.app` address |

Cloud Run picks the service by the host name in each request, so nginx must send each service its own host name rather than your domain's. That is a small change to the ui's nginx settings, made together with this example's template.

The api starts with `uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --workers 1`, without the migration step. The migrate job runs `alembic upgrade head` first.

### Deploying the Google Cloud example

**You need:**
- a Google Cloud project, and the gcloud CLI signed in to it;
- Terraform and Docker on your machine;
- a domain you can point at the load balancer;
- a Qdrant Cloud cluster in your Google Cloud region, with its URL and API key;
- your model provider keys, and your `config.json`.

**The steps:**
1. Copy the example settings file and fill in the project, region, domain, sizes, Evidence Lab version and the names of your keys.
2. Run Terraform to create the network, databases, file share, registry, load balancer and services.
3. Build the web app image with your settings and push it to Artifact Registry.
4. Run the migrate job and wait for it to finish.
5. Point your domain at the load balancer; the managed certificate is issued once it resolves. Open your domain.
6. Run the pipeline job to ingest your documents.

**Upgrading:** set the new Evidence Lab version, rebuild the web app image, run the migrate job, then deploy new revisions of the services.

**Removing the example:** `terraform destroy` removes everything it created. The Qdrant Cloud cluster is removed in Qdrant's console.

## Testing the examples

Each example is tested by deploying it into a test account, subscription or project, and checking that:
- the site answers over HTTPS;
- search, chat, briefs, sign-in and ratings work, and documents and page images open;
- chat streams for over a minute without being cut off by the load balancer or ingress timeout, and an MCP client connects;
- the databases can't be reached from the internet;
- losing an api copy and failing over the database don't lose data or requests;
- an upgrade causes no downtime;
- a database backup restores;
- tear-down leaves nothing behind.

Each example's running cost is measured during its test and added to its section.

## Not included

- **Reprocessing from the admin screens.** The reprocess actions queue background tasks for a Celery worker, which this layout does not run.
- **Large ingestions.** Processing many documents needs far more memory than serving them. Run the pipeline job with enough memory, or run large ingestions elsewhere and copy the results in (see [Database Maintenance](database-maintenance.md)).
