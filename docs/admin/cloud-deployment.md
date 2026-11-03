# Deploying to Cloud Platforms

Evidence Lab runs as a set of containers. On one machine, Docker Compose runs them all, databases included (see [Running from the Published Image](docker-images.md)). On a cloud's managed container service the same images run, with three differences:

- Each service can run several copies behind a load balancer.
- The databases and file storage are the cloud's managed services, not containers.
- A few settings tell the containers where everything is.

This page describes that layout and its settings, with an example deployment for AWS, Azure and Google Cloud.

**On this page**

| Section | What it covers |
|---|---|
| [The cloud layout](#the-cloud-layout) | What runs where, and why the databases are managed services |
| [Settings](#settings) | The settings a load-balanced deployment needs |
| [Example: AWS](#example-aws) | Amazon ECS on Fargate, with step-by-step deploy and teardown |
| [Example: Azure](#example-azure) | Azure Container Apps, with step-by-step deploy and teardown |
| [Example: Google Cloud](#example-google-cloud) | Cloud Run (template not built yet) |
| [Not included](#not-included) | What this layout does not cover |

> **These are demonstration deployments, not a production design.** They show that Evidence Lab runs on each cloud's container service and how the parts fit together. Before running a production service, review the deployment for your organisation, including:
>
> - **Security:** Network access, sign-in settings, how keys and passwords are stored and rotated, and where the Terraform state is kept (it holds generated keys).
> - **Reliability:** Sizes and copies for your traffic, database backups and restores, and failover.
> - **Operations:** Monitoring and alerts, log retention, upgrades and running costs.
> - **Your obligations:** Data protection, data residency, and the terms of the documents you load.

## The cloud layout

Every example uses the same layout. Only the names of the cloud services change.

![What runs where in a cloud deployment](../images/admin/cloud-deployment.png)

### What runs where

| Part | Runs as | Notes |
|---|---|---|
| Load balancer | The cloud's load balancer | The only public entry point. It ends HTTPS and sends all traffic to the ui service. |
| ui | Container service, 2 or more copies | The production web app image (`ui/frontend/Dockerfile.prod`). nginx serves the web app, forwards `/api` to the api, and forwards `/mcp` and `/a2a` to the mcp service. It is built for each deployment, because the build fixes the sign-in mode, data sources and branding into the page. |
| api | Container service, 2 or more copies | The published `astrobagel/evidencelab` image. |
| mcp | Container service, 2 or more copies | The same image, started with `python -m mcp_server.http_server`. |
| embedding | Container service, 1 copy, always running | The `michaelf34/infinity` image. It must keep running, because loading the model takes several minutes. |
| migrate | A job, run before each release starts | The same image, running `alembic upgrade head`. |
| pipeline | A job, run when you ingest documents | The same image, running the pipeline orchestrator. |
| Postgres 16 with pgvector | The cloud's managed Postgres | Backups, a standby copy and patching come with the service. |
| Qdrant | Qdrant Cloud, or Qdrant on a small virtual machine | See below. |
| Redis | The cloud's managed Redis | Holds the rate-limit counts that all api and mcp copies share. |
| Documents and page images | The cloud's network file share | Mounted at `/app/data`. The pipeline writes the files and the api serves them. |

The sizes in the figure come from the memory limits in `docker-compose.prod.yml`.

### Why the databases are managed services

Managed container services don't keep a long-running service's disk when it is redeployed or restarted. On Amazon ECS, a block-storage volume attached to a service's container is deleted when the container stops. Azure Container Apps and Google Cloud Run offer only network file shares and memory. Qdrant needs block storage and does not work on network file systems. So Postgres runs on the cloud's managed Postgres, and Qdrant runs on Qdrant Cloud or on its own virtual machine.

## Settings

Docker Compose needs none of these settings, because the defaults match it. A cloud deployment sets them on the containers listed.

### Where the ui finds the other services

The ui container writes these into its nginx configuration when it starts. If a value is not valid, the container stops with an error.

| Setting | Set on | Default | Set it to |
|---|---|---|---|
| `API_UPSTREAM` | ui | `http://api:8000` | The api service's address, for example `http://api.evidencelab.internal:8000` |
| `MCP_UPSTREAM` | ui | `http://mcp:8001` | The mcp service's address |
| `NGINX_RESOLVER` | ui | `127.0.0.11` (Docker's DNS server) | The cloud network's DNS server |
| `NGINX_REAL_IP_FROM` | ui | `127.0.0.1` (no proxy trusted) | The load balancer's address range, for example `10.0.0.0/16` |

nginx looks up the api and mcp addresses through `NGINX_RESOLVER` while it runs, so it follows a service when the platform replaces it at a new address.

### Visitors' real addresses

Rate limits count requests per visitor address. Behind a load balancer and nginx, every request reaches the api from nginx's address, so without these two settings all visitors share one count.

- **`NGINX_REAL_IP_FROM` on the ui.** nginx takes the visitor's address from the `X-Forwarded-For` header that the load balancer adds. Only proxies in this range are believed, so visitors cannot fake their address. The mcp server rate-limits on the address nginx passes on.
- **`FORWARDED_ALLOW_IPS` on the api.** List the addresses of the ui copies, for example `10.0.0.0/16`. The api then takes the visitor's address from the header nginx sends. Without it, the api trusts only its own machine (`127.0.0.1`).

### Rate limits shared by all copies

| Setting | Set on | Value |
|---|---|---|
| `RATELIMIT_STORAGE_URL` | api, mcp | `redis://<redis-host>:6379/0`, or `rediss://` for Redis over TLS |

Without it, each copy keeps its own counts, so with two copies a visitor gets twice the limit. The sign-in attempt limit (`AUTH_RATE_LIMIT_MAX`) is always counted by each copy separately.

### Postgres over verified TLS

| Setting | Set on | Value |
|---|---|---|
| `PGSSLMODE` | api, mcp, pipeline, migrate | `verify-full` |
| `PGSSLROOTCERT` | api, mcp, pipeline, migrate | The path, inside the container, to the cloud's certificate authority bundle |

Every Postgres connection Evidence Lab makes reads these standard settings. With `verify-full`, a connection is refused unless the server's certificate is signed by that authority and matches `POSTGRES_HOST`. Without them, connections are encrypted when the server supports TLS, but the certificate is not checked.

### Starting the api

Start the api copies without the migration step:

```bash
uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Run `alembic upgrade head` once, as a job, before new api copies start. If every copy migrated at start-up, as the compose files do, they would run the same migration at the same time.

## Example: AWS

This example runs Evidence Lab on Amazon ECS with Fargate. The template and scripts are in [`deploy/aws`](../../deploy/aws/).

![What the AWS example deploys](../images/admin/cloud-aws.png)

### What the AWS example deploys

The sizes are the template's defaults. The demo below uses smaller ones.

| Part | AWS service | Default size |
|---|---|---|
| Network | A VPC (`10.0.0.0/16`) across two availability zones. The load balancer and a NAT gateway are in public subnets. Everything else is in private subnets. | One NAT gateway, through which the containers pull images and reach the model providers |
| Load balancer | Application Load Balancer. With a domain, it serves HTTPS with an ACM certificate and redirects HTTP. Without one, it serves plain HTTP on its own address, for testing only. | Idle timeout of 300 seconds, for streaming chat and MCP |
| ui | ECS service on Fargate (arm64), running the web app image that the deploy script pushes to ECR | 2 tasks, 0.25 vCPU and 0.5 GB each |
| api | ECS service on Fargate (arm64), `astrobagel/evidencelab` | 2 tasks, 2 vCPU and 8 GB each |
| mcp | ECS service on Fargate (arm64), `astrobagel/evidencelab` | 2 tasks, 0.5 vCPU and 2 GB each |
| embedding | ECS service on Fargate (arm64), `michaelf34/infinity:0.0.70` | 1 task, 1 vCPU and 4 GB, always running |
| migrate | ECS task on Fargate, run by the deploy script before the services start | 0.5 vCPU, 1 GB |
| pipeline | ECS task on Fargate, run when you ingest documents | 4 vCPU, 16 GB |
| Postgres | Amazon RDS for PostgreSQL 16, Multi-AZ and encrypted. RDS keeps the password in Secrets Manager. | db.t4g.medium, 50 GB storage, 7 days of backups |
| Qdrant | Qdrant 1.18.3 on an EC2 instance in a private subnet, or your Qdrant Cloud cluster if you set `qdrant_url` | t4g.medium, 30 GB disk |
| Redis | Amazon ElastiCache (Valkey, compatible with Redis), encrypted in transit | cache.t4g.micro |
| Documents and page images | Amazon EFS, mounted at `/app/data` | Elastic throughput |
| Web app image | Amazon ECR repository `<name>/ui` | — |
| Keys and passwords | AWS Secrets Manager: `<name>/app` holds the generated keys, `<name>/providers` any model provider keys | — |
| Model access | An IAM task role for the api, mcp, pipeline and migrate containers, allowed to call Amazon Bedrock models | — |
| Logs | Amazon CloudWatch Logs, one log group per service, `/ecs/<name>/<service>` | 30 days |
| Domain | A Route 53 record pointing at the load balancer, if you set a domain | — |

`<name>` is the deployment name you choose. Every resource is tagged `Deployment=<name>`, so the AWS console's Tag Editor can list them all.

### How the AWS services find each other

The api, mcp and embedding services register their addresses in a private DNS namespace, `<name>.internal` (AWS Cloud Map). The template sets these values:

| Container | Setting | Value |
|---|---|---|
| ui | `API_UPSTREAM` | `http://api.<name>.internal:8000` |
| ui | `MCP_UPSTREAM` | `http://mcp.<name>.internal:8001` |
| ui | `NGINX_RESOLVER` | `10.0.0.2`, the VPC's DNS server |
| ui | `NGINX_REAL_IP_FROM` | `10.0.0.0/16` |
| api | `FORWARDED_ALLOW_IPS` | `10.0.0.0/16` |
| api, mcp, pipeline, migrate | `RATELIMIT_STORAGE_URL` | `rediss://<ElastiCache endpoint>:6379/0` |
| api, mcp, pipeline, migrate | `POSTGRES_HOST` | The RDS endpoint |
| api, mcp, pipeline, migrate | `PGSSLMODE`, `PGSSLROOTCERT` | `verify-full`, and the RDS certificate bundle for the region |
| api, mcp, pipeline, migrate | `QDRANT_HOST`, `QDRANT_API_KEY` | The Qdrant instance's address and generated key, or your Qdrant Cloud URL and key |
| api, mcp, pipeline, migrate | `EMBEDDING_API_URL` | `http://embedding.<name>.internal:7997` |
| api, mcp, pipeline, migrate | `AWS_REGION` | The deployment's region, used for Amazon Bedrock calls |

`config.json` is too large for a container setting. It travels compressed, and each container writes it to `/app/config.json` when it starts.

### Deploying the AWS demo

These steps deploy a demo: 2 World Bank documents, processed with Amazon Bedrock models, on a site anyone with the address can use without signing in. Run every command from the root of the Evidence Lab checkout.

**1. Install the tools.** The tested versions are in brackets.

| Tool | Version | Used for |
|---|---|---|
| [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) | 2.32 or later (2.35.18) | Signing in with `aws login`, and the scripts' AWS calls |
| [Terraform](https://developer.hashicorp.com/terraform/install) | 1.9 or later (1.17.1) | Creating and removing the resources |
| [Docker Desktop](https://docs.docker.com/get-docker/) | A recent version, with buildx | Building the web app image for arm64 (on an Intel or AMD computer Docker builds it through emulation, which is slower) |
| Python 3 and curl | Any recent version | The scripts' helpers and checks |

**2. Get the code** at the release you will deploy, replacing `X.Y.Z` with the version:

```bash
git clone https://github.com/dividor/evidencelab.git
cd evidencelab
git checkout vX.Y.Z
```

**3. Sign in to AWS.** This example uses the profile name `evidencelab` and the region `us-east-2`.

```bash
aws configure set region us-east-2 --profile evidencelab
aws login --region us-east-2 --profile evidencelab
export AWS_PROFILE=evidencelab
```

`aws login` opens your browser to sign in. Check which account the scripts will use with `aws sts get-caller-identity`.

**4. Create the settings file:**

```bash
cp deploy/aws/terraform.tfvars.example deploy/aws/terraform.tfvars
```

Edit `deploy/aws/terraform.tfvars`:

| Setting | What to set |
|---|---|
| `name` | A short name for this deployment, for example `evidencelab-demo`. |
| `region` | The region you signed in to, for example `us-east-2`. |
| `evidencelab_version` | The same version you checked out, for example `X.Y.Z`. |
| `config_json_path` | Leave as `"../../config.json"`. The demo uses its own configuration. |
| `domain_name`, `route53_zone_id` | Leave empty. The demo is served over plain HTTP on the load balancer's address. |
| `qdrant_url` | Leave empty, to run Qdrant on EC2. |
| The `#` lines at the end | Remove the `#` from each line, for smaller and cheaper single-zone settings. |

If your AWS account is on the Free plan, check you removed the `#` from the `qdrant_instance_type = "t4g.small"` line, and add the line below. The Free plan refuses the default Qdrant server size and the default of 7 days of database backups.

```
db_backup_retention_days = 1
```

**5. Check the Bedrock models.** The demo uses the **AWS Bedrock** models in `config.json`: Titan Text Embeddings V2, Amazon Nova 2 Lite and Cohere Rerank 3.5. No model keys are needed, because the containers call Bedrock with their task role. Check your region offers the first two:

```bash
aws bedrock list-foundation-models --region us-east-2 \
  --query "modelSummaries[?modelId=='amazon.titan-embed-text-v2:0' || modelId=='amazon.nova-2-lite-v1:0'].modelId"
```

Both IDs should be listed. If your region is outside the United States, or offers different models, edit the Bedrock entries in `config.json` first, as described in [Amazon Bedrock](pipeline-configuration.md#amazon-bedrock). Cohere Rerank 3.5 is called in `us-west-2`, because us-east-2 does not offer it.

To use Azure Foundry models instead, set `AZURE_FOUNDRY_KEY` and `AZURE_FOUNDRY_ENDPOINT` and add `--provider azure_foundry` to the command in step 6. The deploy script copies the keys into Secrets Manager.

**6. Deploy:**

```bash
deploy/aws/scripts/deploy.sh --demo 2
```

Terraform asks you to type `yes` twice: once to create the infrastructure, and once to start the services. The script runs these steps and prints each one as it starts:

1. Writes the demo configuration to `deploy/aws/.demo/`.
2. Creates the network, database, Redis, file share, Qdrant, image registry, load balancer and ECS cluster.
3. Stores any model provider keys in Secrets Manager (none for Bedrock).
4. Builds the web app image and pushes it to ECR.
5. Runs the database migrations.
6. Starts the services, and waits until they are all running.
7. Downloads 2 World Bank documents and processes them.
8. Checks that the site answers, and prints its address.

With `--demo`, the web app is built with the site's API key, so visitors can use the site without signing in, as on evidencelab.ai. Anyone who opens the site can read that key from the page, so use `--demo` only for demonstrations.

**7. Try it.** Open the address the script printed. Choose the dataset **Demo Data from World Bank**, and search for *What types of fraud are most commonly reported?*

**8. Remove everything:**

```bash
deploy/aws/scripts/teardown.sh
```

Terraform lists what it will delete and asks you to type `yes`. The database, file share and Qdrant are deleted with all their data. The script then checks that Terraform manages nothing more for the deployment, and prints `Everything Terraform created for <name> is deleted.` It also prints a command to list anything else tagged with the deployment name. AWS's tag list keeps showing deleted resources for a while, so run that command later if you want to check.

### Deploying your own documents

1. In `deploy/aws/terraform.tfvars`, set `config_json_path` to your `config.json`. If it uses models from other providers than Amazon Bedrock, set `provider_secret_names` to the names of their keys, for example `["AZURE_FOUNDRY_KEY", "AZURE_FOUNDRY_ENDPOINT"]`, and export those keys.
2. Run `deploy/aws/scripts/deploy.sh` without `--demo`. Visitors must sign in, because the web app carries no API key. To let them use the site signed out, add `anonymous_access = true`, which puts the key in the page.
3. Ingest documents with the pipeline task, replacing `<data_subdir>` with the data source's `data_subdir` in your `config.json`:

```bash
deploy/aws/scripts/run-task.sh pipeline python -m pipeline.orchestrator --data-source <data_subdir>
```

### Upgrading

1. Check out the new release of the code.
2. Set the new `evidencelab_version` in `deploy/aws/terraform.tfvars`.
3. Run `deploy/aws/scripts/deploy.sh` again, with `--demo 2` if the deployment is the demo.

The script applies any changes, rebuilds the web app image, runs the migrations and then replaces the services' tasks.

## Example: Azure

This example runs Evidence Lab on Azure Container Apps. The template and scripts are in [`deploy/azure`](../../deploy/azure/). Everything it creates is in one new resource group, named after the deployment.

![What the Azure example deploys](../images/admin/cloud-azure.png)

### What the Azure example deploys

The sizes are the template's defaults. The demo below uses smaller ones.

| Part | Azure service | Default size |
|---|---|---|
| Resource group | A new resource group named `<name>`, holding everything below. The first apply stops if a resource group of that name already exists. | — |
| Network | A virtual network (`10.0.0.0/16`) with a subnet for the Container Apps environment, one for Postgres, and one for Qdrant and the Redis private endpoint. A NAT gateway gives outbound internet access. Nothing in the network has a public address of its own. | One NAT gateway, through which the apps pull images and reach the models |
| Entry point | The ui app's ingress. Container Apps serves it over HTTPS at `https://ui.<environment domain>`, with a certificate it manages, and redirects plain HTTP. | — |
| Container platform | A Container Apps environment with the Consumption workload profile, in the network | Up to 4 vCPU and 8 GB per container |
| ui | Container app, running the web app image that the deploy script pushes to the registry | 2 replicas, 0.25 vCPU and 0.5 GB each |
| api | Container app, `astrobagel/evidencelab` | 2 replicas, 4 vCPU and 8 GB each |
| mcp | Container app, `astrobagel/evidencelab` | 2 replicas, 1 vCPU and 2 GB each |
| embedding | Container app, `michaelf34/infinity:0.0.70` | 1 replica, 2 vCPU and 4 GB, always running |
| migrate | Container Apps job, run by the deploy script before the apps start | 0.5 vCPU, 1 GB |
| pipeline | Container Apps job, run when you ingest documents | 4 vCPU, 8 GB, the Consumption profile's largest |
| Postgres | Azure Database for PostgreSQL flexible server 16, with a standby in a second zone, reachable only inside the network | General Purpose D2ds_v5, 128 GB storage, 7 days of backups |
| Qdrant | Qdrant 1.18.3 on an Ubuntu virtual machine with no public address, or your Qdrant Cloud cluster if you set `qdrant_url` | Standard_B2s, 30 GB disk |
| Redis | Azure Managed Redis, reachable only through a private endpoint, over TLS | Balanced_B0, with a replica |
| Documents and page images | An Azure Files share, mounted at `/app/data`, accepting connections only from the apps' subnet | 100 GB quota |
| Web app image | Azure Container Registry. The apps pull from it with a managed identity. | Basic |
| Models | An Azure AI Foundry resource with the models in `config.json`'s **Azure Foundry** set: `text-embedding-3-small`, `gpt-4.1-mini` and `Cohere-rerank-v4.0-fast` | Global Standard deployments. The reranker gets capacity 20, which allows 20 requests and 20,000 tokens a minute. |
| Keys and passwords | Container Apps secrets on each app and job, generated by Terraform | — |
| Logs | A Log Analytics workspace, holding every app's and job's output | 30 days |

`<name>` is the deployment name you choose. Every resource is tagged `Deployment=<name>`.

### How the Azure apps find each other

Apps in a Container Apps environment reach each other by app name. The api, mcp and embedding apps take plain TCP connections: the environment's HTTP routing picks an app by the request's host name, and nginx passes on the visitor's host name, so HTTP routing would not reach the api.

Containers in the environment look names up through `127.0.0.11`, and complete a bare app name such as `api` with the search domain `k8se-apps.svc.cluster.local`. nginx does not use search domains, so the ui is given the full names. Requests reach the ui, and the ui's requests reach the api, from the environment's own proxies, whose addresses are in `100.100.0.0/16`. The template sets these values:

| Container | Setting | Value |
|---|---|---|
| ui | `API_UPSTREAM` | `http://api.k8se-apps.svc.cluster.local:8000` |
| ui | `MCP_UPSTREAM` | `http://mcp.k8se-apps.svc.cluster.local:8001` |
| ui | `NGINX_RESOLVER` | `127.0.0.11` |
| ui | `NGINX_REAL_IP_FROM` | `100.100.0.0/16` |
| api | `FORWARDED_ALLOW_IPS` | `100.100.0.0/16` |
| api, mcp, pipeline, migrate | `RATELIMIT_STORAGE_URL` | `rediss://` with the Redis key, address and port, from a secret |
| api, mcp, pipeline, migrate | `POSTGRES_HOST` | The flexible server's address, `<server>.postgres.database.azure.com` |
| api, mcp, pipeline, migrate | `PGSSLMODE`, `PGSSLROOTCERT` | `verify-full`, and `/etc/ssl/certs/ca-certificates.crt`. Azure's Postgres certificates chain to roots already in the image. |
| api, mcp, pipeline, migrate | `QDRANT_HOST`, `QDRANT_API_KEY` | The Qdrant machine's address and generated key, or your Qdrant Cloud URL and key |
| api, mcp, pipeline, migrate | `EMBEDDING_API_URL` | `http://embedding:7997` |
| api, mcp, pipeline, migrate | `AZURE_FOUNDRY_ENDPOINT`, `AZURE_FOUNDRY_KEY` | The deployment's own Foundry resource, `https://<resource>.openai.azure.com/`, and its key |

As on AWS, `config.json` travels compressed and each container writes it to `/app/config.json` when it starts.

### Deploying the Azure demo

These steps deploy a demo: 2 World Bank documents, processed with the deployment's own Azure AI Foundry models, on a site anyone with the address can use without signing in. Run every command from the root of the Evidence Lab checkout.

**1. Install the tools.** The tested versions are in brackets.

| Tool | Version | Used for |
|---|---|---|
| [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) | 2.81 or later (2.81.0) | Signing in with `az login`, and the scripts' Azure calls |
| [Terraform](https://developer.hashicorp.com/terraform/install) | 1.9 or later (1.17.1) | Creating and removing the resources |
| [Docker Desktop](https://docs.docker.com/get-docker/) | A recent version, with buildx | Building the web app image for amd64 (on an Apple silicon Mac Docker builds it through emulation, which is slower) |
| Python 3 and curl | Any recent version | The scripts' helpers and checks |

**2. Get the code** at the release you will deploy, replacing `X.Y.Z` with the version:

```bash
git clone https://github.com/dividor/evidencelab.git
cd evidencelab
git checkout vX.Y.Z
```

**3. Sign in to Azure** and note your subscription's ID:

```bash
az login
az account show --query "{name:name, id:id}"
```

`az login` opens your browser to sign in. Your account needs the Owner role on the subscription, because the template gives the apps permission to pull from the registry. If `az account show` names the wrong subscription, run `az account set --subscription <id>`.

**4. Create the settings file:**

```bash
cp deploy/azure/terraform.tfvars.example deploy/azure/terraform.tfvars
```

Edit `deploy/azure/terraform.tfvars`:

| Setting | What to set |
|---|---|
| `subscription_id` | The ID that `az account show` printed. |
| `name` | A short name for this deployment, for example `evidencelab-demo`. It is also the name of the new resource group, so it must not be the name of one you already have. |
| `location` | The region, for example `eastus2`. |
| `evidencelab_version` | The same version you checked out, for example `X.Y.Z`. |
| `config_json_path` | Leave as `"../../config.json"`. The demo uses its own configuration. |
| `qdrant_url` | Leave empty, to run Qdrant on a virtual machine. |
| The `#` lines at the end | Remove the `#` from each line, for smaller and cheaper single-zone settings. The database keeps the smallest General Purpose size: in testing, Azure refused the cheaper Burstable sizes in eastus2 with `SkuNotAvailable`. |

**5. Check your region offers the models.** The template deploys `text-embedding-3-small`, `gpt-4.1-mini` and `Cohere-rerank-v4.0-fast` as Global Standard deployments. List what your region offers:

```bash
az cognitiveservices model list --location eastus2 \
  --query "[?model.name=='text-embedding-3-small' || model.name=='gpt-4.1-mini' || model.name=='Cohere-rerank-v4.0-fast'].model.name" -o tsv | sort -u
```

All three names should be listed. If your subscription has no quota for one of them, the first apply stops with an error naming it. Request quota in the Azure AI Foundry portal, or choose another region.

The reranker's quota is shared by every Foundry resource in your subscription and region. Check how much is free with this command, which prints the units in use and the limit:

```bash
az cognitiveservices usage list --location eastus2 \
  --query "[?name.value=='AIServices.GlobalStandard.Cohere-Rerank-V4-Fast'].[currentValue, limit]" -o tsv
```

The template takes 20 units. If fewer are free, set a lower `capacity` for `Cohere-rerank-v4.0-fast` in `model_deployments` (copy the whole setting from `deploy/azure/variables.tf` into `terraform.tfvars`). In testing, 1 unit was too few: the first search failed with a reranker error (HTTP 429, too many requests). 19 units worked.

**6. Deploy:**

```bash
deploy/azure/scripts/deploy.sh --demo 2
```

Terraform asks you to type `yes` twice: once to create the infrastructure, and once to start the apps. The script runs these steps and prints each one as it starts:

1. Writes the demo configuration to `deploy/azure/.demo/`.
2. Creates the resource group, network, database, Redis, file share, Qdrant, registry, models, Container Apps environment and jobs.
3. Builds the web app image and pushes it to the registry.
4. Runs the database migrations.
5. Creates the ui, api, mcp and embedding apps, and waits until they are all running.
6. Downloads 2 World Bank documents and processes them.
7. Checks that the site answers, and prints its address.

With `--demo`, the web app is built with the site's API key, so visitors can use the site without signing in, as on evidencelab.ai. Anyone who opens the site can read that key from the page, so use `--demo` only for demonstrations.

**7. Try it.** Open the address the script printed. Choose the dataset **Demo Data from World Bank**, and search for *What types of fraud are most commonly reported?*

**8. Remove everything:**

```bash
deploy/azure/scripts/teardown.sh
```

Terraform lists what it will delete and asks you to type `yes`. The database, file share and Qdrant are deleted with all their data, and the Foundry resource is purged so its name and quota are free at once. The script then checks that Terraform manages nothing more and that the resource group is gone, and prints `Everything Terraform created for <name> is deleted, and the resource group is gone.`

The template registers the Azure services it uses with your subscription (for example `Microsoft.App`). These registrations are subscription settings that stay after teardown. They cost nothing.

### Deploying your own documents

1. In `deploy/azure/terraform.tfvars`, set `config_json_path` to your `config.json`. Its models can be the deployment's own (the **Azure Foundry** set). For models from other providers, add their keys as `provider_secrets`, for example `provider_secrets = { HUGGINGFACE_API_KEY = "..." }`. They become Container Apps secrets and are kept in Terraform's state.
2. Run `deploy/azure/scripts/deploy.sh` without `--demo`. Visitors must sign in, because the web app carries no API key. To let them use the site signed out, add `anonymous_access = true`, which puts the key in the page.
3. Ingest documents with the pipeline job, replacing `<data_subdir>` with the data source's `data_subdir` in your `config.json`:

```bash
deploy/azure/scripts/run-job.sh pipeline python -m pipeline.orchestrator --data-source <data_subdir>
```

### Upgrading

1. Check out the new release of the code.
2. Set the new `evidencelab_version` in `deploy/azure/terraform.tfvars`.
3. Run `deploy/azure/scripts/deploy.sh` again, with `--demo 2` if the deployment is the demo.

The script applies any changes, builds a new web app image, runs the migrations and then moves each app to a new revision.

## Example: Google Cloud

> **Not built yet.** There is no Google Cloud template yet, and nothing in this section has been tested. It is a plan: the services and sizes are a starting point, and they may change when the template is built and tested. Step-by-step instructions will be added with the template, as for AWS and Azure.

This example will run Evidence Lab on Cloud Run, with Cloud SQL for PostgreSQL, Qdrant Cloud, Memorystore and Filestore, behind an external Application Load Balancer.

![What the Google Cloud example deploys](../images/admin/cloud-gcp.png)

| Part | Google Cloud service | Planned size |
|---|---|---|
| Network | A VPC network. Cloud Run reaches it with Direct VPC egress. Cloud SQL, Memorystore and Filestore use private addresses in it. | — |
| Load balancer | Global external Application Load Balancer with a Google-managed certificate | — |
| ui | Cloud Run service, running your web app image from Artifact Registry, reachable only through the load balancer | At least 2 instances, 1 vCPU and 512 MB |
| api | Cloud Run service, `astrobagel/evidencelab`, internal traffic only, with CPU kept allocated for streaming answers | At least 2 instances, 2 vCPU and 8 GB |
| mcp | Cloud Run service, `astrobagel/evidencelab`, internal traffic only | At least 2 instances, 1 vCPU and 2 GB |
| embedding | Cloud Run service, `michaelf34/infinity:0.0.70`, internal traffic only | At least 1 instance, 2 vCPU and 4 GB |
| migrate | Cloud Run job, run before each release | 1 vCPU, 1 GB |
| pipeline | Cloud Run job, run when you ingest documents | 4 vCPU, 16 GB |
| Postgres | Cloud SQL for PostgreSQL 16, regional high availability, private address only | 2 vCPU, 8 GB, 50 GB SSD |
| Qdrant | Qdrant Cloud cluster in the same Google Cloud region | Sized from your collection |
| Redis | Memorystore for Redis, encrypted in transit | Basic tier, 1 GB |
| Documents and page images | Filestore share, mounted at `/app/data` | Sized from your data |
| Keys, logs and domain | Secret Manager, Cloud Logging and Cloud DNS | — |

To check when the template is built:

- How the ui reaches the api and mcp services. nginx forwards each visitor's host name to the api, and Cloud Run may pick the service by host name, as Azure Container Apps does for HTTP. The Azure example avoids this with plain TCP between the apps.
- Which address ranges the load balancer and the ui connect from, for `NGINX_REAL_IP_FROM` and `FORWARDED_ALLOW_IPS`.
- The Memorystore and Filestore sizes and settings.

## Not included

- **Reprocessing from the admin screens.** The reprocess actions queue tasks for a Celery worker, which this layout does not run.
- **Large ingestions.** Processing many documents needs far more memory than serving them. Give the pipeline task more memory, or run large ingestions elsewhere and copy the results in (see [Database Maintenance](database-maintenance.md)). On Azure, the Consumption profile stops at 8 GB per container.
- **Your own domain on Azure.** The Azure example serves the site at its Container Apps address. The template does not set up a custom domain.
