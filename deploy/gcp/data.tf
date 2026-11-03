# Postgres, Redis, the document bucket, Qdrant, the generated keys and
# their secrets, the web app image registry, and the service account the
# containers run as.

data "google_project" "this" {}

resource "random_string" "suffix" {
  # Bucket names are global, and Cloud SQL names stay taken for a week after
  # deletion, so each deployment adds a suffix of its own.
  length  = 6
  upper   = false
  special = false
}

# Postgres, reachable only on the private connection, over verified TLS.
resource "google_sql_database_instance" "main" {
  # A deleted instance's name cannot be reused for up to a week, so each
  # deployment adds its suffix, and a redeploy after teardown does not clash.
  name                = "${var.name}-${random_string.suffix.result}"
  database_version    = "POSTGRES_16"
  deletion_protection = var.db_deletion_protection

  settings {
    # db-custom machine types belong to the Enterprise edition; Postgres 16
    # otherwise defaults to Enterprise Plus.
    edition           = "ENTERPRISE"
    tier              = var.db_tier
    availability_type = var.db_high_availability ? "REGIONAL" : "ZONAL"
    disk_size         = var.db_disk_gb
    disk_autoresize   = true
    user_labels       = { deployment = var.name }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
      ssl_mode        = "ENCRYPTED_ONLY"
      server_ca_mode  = "GOOGLE_MANAGED_CAS_CA"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
  }

  depends_on = [google_service_networking_connection.services]
}

# The server's certificate names the instance's private DNS name, so the
# containers must connect by that name to verify it. Cloud SQL reports the
# name but does not publish it, so this private zone, seen only inside the
# network, points it at the private address.
locals {
  postgres_host = trimsuffix(one([for d in google_sql_database_instance.main.dns_names : d.name if d.connection_type == "PRIVATE_SERVICES_ACCESS"]), ".")
}

resource "google_dns_managed_zone" "postgres" {
  name       = "${var.name}-postgres"
  dns_name   = "${local.postgres_host}."
  visibility = "private"

  private_visibility_config {
    networks {
      network_url = google_compute_network.main.id
    }
  }
}

resource "google_dns_record_set" "postgres" {
  managed_zone = google_dns_managed_zone.postgres.name
  name         = google_dns_managed_zone.postgres.dns_name
  type         = "A"
  ttl          = 300
  rrdatas      = [google_sql_database_instance.main.private_ip_address]
}

resource "google_sql_database" "main" {
  name     = "evidencelab"
  instance = google_sql_database_instance.main.name
}

resource "random_password" "postgres" {
  length  = 40
  special = false
}

resource "google_sql_user" "main" {
  name     = "evidencelab"
  instance = google_sql_database_instance.main.name
  password = random_password.postgres.result
}

# Redis holds the rate-limit counts that every api and mcp copy shares.
resource "google_redis_instance" "main" {
  name                    = var.name
  tier                    = var.redis_tier
  memory_size_gb          = var.redis_memory_gb
  redis_version           = "REDIS_7_2"
  authorized_network      = google_compute_network.main.id
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"

  depends_on = [google_service_networking_connection.services]
}

# Documents and page images, mounted at /app/data in every container that
# needs them. Deleting the deployment deletes the bucket and its contents.
resource "google_storage_bucket" "data" {
  name                        = "${var.name}-data-${random_string.suffix.result}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true
  depends_on                  = [google_project_service.this]
}

# Qdrant needs block storage, which Cloud Run does not offer, so it runs on a
# small virtual machine of its own, with no public address.
locals {
  qdrant_on_vm = var.qdrant_url == ""
  qdrant_url   = local.qdrant_on_vm ? "http://${google_compute_instance.qdrant[0].network_interface[0].network_ip}:6333" : var.qdrant_url
  qdrant_key   = local.qdrant_on_vm ? random_password.qdrant_api_key.result : var.qdrant_api_key
  qdrant_image = "qdrant/qdrant:v1.18.3"
}

resource "random_password" "qdrant_api_key" {
  length  = 40
  special = false
}

resource "google_compute_instance" "qdrant" {
  count        = local.qdrant_on_vm ? 1 : 0
  name         = "${var.name}-qdrant"
  machine_type = var.qdrant_machine_type
  zone         = "${var.region}-a"
  tags         = ["${var.name}-qdrant"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = var.qdrant_disk_gb
      type  = "pd-balanced"
    }
  }

  # No access_config block: the machine gets no public address, and reaches
  # the internet through Cloud NAT.
  network_interface {
    subnetwork = google_compute_subnetwork.main.id
  }

  shielded_instance_config {
    enable_secure_boot = true
  }

  # Docker runs Qdrant with its storage on the machine's disk. The script runs
  # on every boot: it creates the container on the first, and Docker's restart
  # policy starts it on the others. Changing the key or image replaces the
  # machine.
  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -euo pipefail
    if ! command -v docker >/dev/null; then
      apt-get update
      apt-get install -y docker.io
    fi
    systemctl enable --now docker
    if ! docker container inspect qdrant >/dev/null 2>&1; then
      mkdir -p /var/lib/qdrant/storage
      docker run -d --name qdrant --restart always -p 6333:6333 \
        -v /var/lib/qdrant/storage:/qdrant/storage \
        -e QDRANT__SERVICE__API_KEY='${random_password.qdrant_api_key.result}' \
        ${local.qdrant_image}
    fi
  EOT

  depends_on = [google_compute_router_nat.main]
}

# The keys the api signs and encrypts with.
resource "random_password" "api_secret_key" {
  length  = 48
  special = false
}

resource "random_password" "auth_secret_key" {
  length  = 64
  special = false
}

# A Fernet key: 32 random bytes in URL-safe base64.
resource "random_bytes" "key_encryption_key" {
  length = 32
}

# The secret settings, by setting name. Each is stored in Secret Manager as
# <name>-<setting in lower case with hyphens>, and the containers read it
# from there.
locals {
  secret_settings = merge(var.provider_secrets, {
    API_SECRET_KEY        = random_password.api_secret_key.result
    AUTH_SECRET_KEY       = random_password.auth_secret_key.result
    KEY_ENCRYPTION_KEY    = replace(replace(random_bytes.key_encryption_key.base64, "+", "-"), "/", "_")
    QDRANT_API_KEY        = local.qdrant_key
    POSTGRES_PASSWORD     = random_password.postgres.result
    RATELIMIT_STORAGE_URL = "rediss://:${google_redis_instance.main.auth_string}@${google_redis_instance.main.host}:${google_redis_instance.main.port}/0?ssl_ca_certs=/tmp/redis-ca.pem"
  })
  secret_ids = { for k in nonsensitive(keys(local.secret_settings)) : k => "${var.name}-${lower(replace(k, "_", "-"))}" }
}

resource "google_secret_manager_secret" "this" {
  for_each  = local.secret_ids
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "this" {
  for_each    = local.secret_ids
  secret      = google_secret_manager_secret.this[each.key].id
  secret_data = local.secret_settings[each.key]
}

# Cloud Run does not pull these images from Docker Hub itself: it looked for
# them on Google's Docker Hub mirror, which did not have the Evidence Lab
# image. This repository fetches them from Docker Hub and keeps a copy.
resource "google_artifact_registry_repository" "dockerhub" {
  repository_id = "${var.name}-dockerhub"
  location      = var.region
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"

  remote_repository_config {
    description = "Docker Hub"
    docker_repository {
      public_repository = "DOCKER_HUB"
    }
  }

  depends_on = [google_project_service.this]
}

# The web app image, built and pushed for each deployment by
# scripts/build-ui-image.sh.
resource "google_artifact_registry_repository" "main" {
  repository_id = var.name
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.this]
}

# The containers run as this account. It may call Vertex AI (Gemini and
# embeddings), the Vertex ranker, read the secrets and use the bucket.
resource "google_service_account" "run" {
  account_id   = "${var.name}-run"
  display_name = "Evidence Lab containers (${var.name})"
  depends_on   = [google_project_service.this]
}

# Vertex ranking needs discoveryengine.rankingConfigs.rank, which the
# Discovery Engine viewer role has and the user role does not.
resource "google_project_iam_member" "run" {
  for_each = toset(["roles/aiplatform.user", "roles/discoveryengine.viewer"])
  project  = var.project_id
  role     = each.value
  member   = google_service_account.run.member
}

resource "google_secret_manager_secret_iam_member" "run" {
  for_each  = google_secret_manager_secret.this
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.run.member
}

resource "google_storage_bucket_iam_member" "run" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectUser"
  member = google_service_account.run.member
}
