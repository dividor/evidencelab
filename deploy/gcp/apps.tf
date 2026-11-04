# The Cloud Run web and embedding services, and the migrate and pipeline
# jobs.
#
# Cloud Run picks the service for each request by its host name, and nginx
# passes on the visitor's, so nginx could not reach a separate api service.
# The web service therefore runs the ui, api and mcp containers together in
# each instance, where nginx reaches the api and mcp on localhost.

locals {
  # Cloud Run service addresses are https://<service>-<project number>.<region>.run.app,
  # known before the services exist, so the jobs can be given them on the
  # first apply.
  run_domain      = "${data.google_project.this.number}.${var.region}.run.app"
  site_url        = "https://${var.name}-web-${local.run_domain}"
  embedding_url   = "https://${var.name}-embedding-${local.run_domain}"
  dockerhub       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.dockerhub.repository_id}"
  app_image       = "${local.dockerhub}/${var.evidencelab_image}:${var.evidencelab_version}"
  embedding_image = "${local.dockerhub}/${var.embedding_image}"
  # Containers resolve names through the metadata server, which also
  # answers for the network's private zones.
  dns_server = "169.254.169.254"
  # Cloud Run's front end connects to nginx from a link-local address
  # (measured: 169.254.169.126), so nginx takes the visitor's address from
  # the X-Forwarded-For header it adds.
  front_end_cidr = "169.254.0.0/16"
  ui_image       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}/ui:${var.ui_image_tag}"

  # config.json is too big for a container setting (92 KB), so it travels
  # compressed and is written to /app/config.json when the container starts,
  # together with the Cloud SQL and Memorystore certificate authorities.
  prepare_and_run = join(" ", [
    "python -c 'import base64, gzip, os;",
    "open(\"/app/config.json\", \"wb\").write(gzip.decompress(base64.b64decode(os.environ[\"EVIDENCELAB_CONFIG_GZ\"])));",
    "open(\"/tmp/pg-ca.pem\", \"w\").write(os.environ[\"PG_CA_CERT\"]);",
    "open(\"/tmp/redis-ca.pem\", \"w\").write(os.environ[\"REDIS_CA_CERT\"])'",
    "&& exec \"$@\"",
  ])

  app_environment = merge(var.extra_environment, {
    EVIDENCELAB_CONFIG_GZ = base64gzip(file(var.config_json_path))
    PG_CA_CERT            = google_sql_database_instance.main.server_ca_cert[0].cert
    REDIS_CA_CERT         = google_redis_instance.main.server_ca_certs[0].cert
    QDRANT_HOST           = local.qdrant_url
    # The certificate's name ends with a dot, and both Postgres drivers
    # (psycopg2 and asyncpg) match it only when the host does too.
    POSTGRES_HOST         = google_dns_record_set.postgres.name
    POSTGRES_PORT         = "5432"
    POSTGRES_DB           = google_sql_database.main.name
    POSTGRES_USER         = google_sql_user.main.name
    PGSSLMODE             = "verify-full"
    PGSSLROOTCERT         = "/tmp/pg-ca.pem"
    EMBEDDING_API_URL     = local.embedding_url
    DATA_MOUNT_PATH       = "/app/data"
    PYTHONPATH            = "/app"
    GOOGLE_CLOUD_PROJECT  = var.project_id
    GOOGLE_CLOUD_LOCATION = var.vertex_location
    USER_MODULE           = var.user_module
    APP_BASE_URL          = local.site_url
    CORS_ALLOWED_ORIGINS  = local.site_url
    AUTH_COOKIE_SECURE    = "true"
  })

  jobs = {
    migrate = {
      args    = ["alembic", "upgrade", "head"]
      size    = var.migrate_job
      timeout = "1800s"
    }
    # Always started with its own command by scripts/run-job.sh.
    pipeline = {
      args    = ["python", "-m", "pipeline.orchestrator", "--help"]
      size    = var.pipeline_job
      timeout = "${var.pipeline_timeout_hours * 3600}s"
    }
  }
}

resource "google_cloud_run_v2_service" "web" {
  count               = var.services_enabled ? 1 : 0
  name                = "${var.name}-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  # The site is public: anyone may call it, and the api checks API keys and
  # sign-in itself.
  invoker_iam_disabled = true

  template {
    service_account       = google_service_account.run.email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    # Long enough for streamed chat answers and MCP sessions.
    timeout = "3600s"

    scaling {
      min_instance_count = var.web.min_instances
      max_instance_count = var.web.max_instances
    }

    # All outbound traffic goes through the network, so the containers reach
    # Qdrant, Cloud SQL, Memorystore and the internal embedding service.
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = google_compute_network.main.id
        subnetwork = google_compute_subnetwork.main.id
      }
    }

    containers {
      name       = "ui"
      image      = local.ui_image
      depends_on = ["api", "mcp"]

      ports {
        container_port = 80
      }
      resources {
        limits = var.web.ui
      }
      env {
        name  = "API_UPSTREAM"
        value = "http://127.0.0.1:8000"
      }
      env {
        name  = "MCP_UPSTREAM"
        value = "http://127.0.0.1:8001"
      }
      env {
        name  = "NGINX_RESOLVER"
        value = local.dns_server
      }
      env {
        name  = "NGINX_REAL_IP_FROM"
        value = local.front_end_cidr
      }
    }

    # The api and mcp listen on all addresses: Cloud Run's startup checks do
    # not reach a server listening on 127.0.0.1 only (the checks failed 55
    # times while both were up there). Outside traffic still reaches only the
    # ui, the one container with a port.
    dynamic "containers" {
      for_each = {
        api = { args = ["uvicorn", "ui.backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"], port = 8000, size = var.web.api, env = { API_ROOT_PATH = "/api" } }
        mcp = { args = ["python", "-m", "mcp_server.http_server"], port = 8001, size = var.web.mcp, env = {} }
      }
      content {
        name    = containers.key
        image   = local.app_image
        command = ["sh", "-c", local.prepare_and_run, "evidencelab"]
        args    = containers.value.args

        resources {
          limits = containers.value.size
        }

        dynamic "env" {
          for_each = merge(local.app_environment, containers.value.env)
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.secret_ids
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.this[env.key].secret_id
                version = "latest"
              }
            }
          }
        }

        startup_probe {
          tcp_socket {
            port = containers.value.port
          }
          period_seconds    = 10
          failure_threshold = 60
        }

        volume_mounts {
          name       = "data"
          mount_path = "/app/data"
        }
      }
    }

    volumes {
      name = "data"
      gcs {
        bucket    = google_storage_bucket.data.name
        read_only = false
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.run,
    google_secret_manager_secret_version.this,
    google_cloud_run_v2_service.embedding,
  ]
}

resource "google_cloud_run_v2_service" "embedding" {
  count                = var.services_enabled ? 1 : 0
  name                 = "${var.name}-embedding"
  location             = var.region
  deletion_protection  = false
  ingress              = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  invoker_iam_disabled = true

  template {
    service_account = google_service_account.run.email

    # Loading the model takes minutes, so one instance always runs, with its
    # CPU allocated between requests.
    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    containers {
      image = local.embedding_image
      args  = ["v2"]

      ports {
        container_port = 7997
      }
      resources {
        limits   = var.embedding
        cpu_idle = false
      }
      env {
        name  = "INFINITY_MODEL_ID"
        value = var.embedding_model
      }
      env {
        name  = "INFINITY_BATCH_SIZE"
        value = "8"
      }
      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }

      # Downloading and loading the model can take 10 minutes or more.
      startup_probe {
        tcp_socket {
          port = 7997
        }
        period_seconds    = 10
        failure_threshold = 180
      }
    }
  }

  depends_on = [google_project_service.this]
}

resource "google_cloud_run_v2_job" "this" {
  for_each            = local.jobs
  name                = "${var.name}-${each.key}"
  location            = var.region
  deletion_protection = false

  template {
    task_count = 1

    template {
      service_account       = google_service_account.run.email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      timeout               = each.value.timeout
      max_retries           = 0

      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.main.id
          subnetwork = google_compute_subnetwork.main.id
        }
      }

      containers {
        name    = each.key
        image   = local.app_image
        command = ["sh", "-c", local.prepare_and_run, "evidencelab"]
        args    = each.value.args

        resources {
          limits = each.value.size
        }

        dynamic "env" {
          for_each = local.app_environment
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.secret_ids
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.this[env.key].secret_id
                version = "latest"
              }
            }
          }
        }

        volume_mounts {
          name       = "data"
          mount_path = "/app/data"
        }
      }

      volumes {
        name = "data"
        gcs {
          bucket    = google_storage_bucket.data.name
          read_only = false
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.run,
    google_secret_manager_secret_version.this,
    google_storage_bucket_iam_member.run,
  ]
}
