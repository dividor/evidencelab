# The Container Apps environment, the ui, api, mcp and embedding apps, and
# the migrate and pipeline jobs.

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.name}-logs"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = var.name
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  infrastructure_subnet_id   = azurerm_subnet.apps.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  logs_destination           = "log-analytics"
  tags                       = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  depends_on = [azurerm_subnet_nat_gateway_association.this]
}

resource "azurerm_container_app_environment_storage" "data" {
  name                         = "data"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.data.name
  share_name                   = azurerm_storage_share.data.name
  access_key                   = azurerm_storage_account.data.primary_access_key
  access_mode                  = "ReadWrite"
}

locals {
  site_url  = "https://ui.${azurerm_container_app_environment.main.default_domain}"
  app_image = "${var.evidencelab_image}:${var.evidencelab_version}"

  # Apps in the environment reach each other by app name. The api, mcp and
  # embedding apps take plain TCP: the environment's HTTP routing picks the
  # app by Host header, and nginx passes on the visitor's. Containers resolve
  # names through 127.0.0.11, as under Docker, and complete a bare app name
  # with the search domain k8se-apps.svc.cluster.local. nginx does not use
  # search domains, so the ui is given the full names.
  dns_server    = "127.0.0.11"
  api_url       = "http://api.k8se-apps.svc.cluster.local:8000"
  mcp_url       = "http://mcp.k8se-apps.svc.cluster.local:8001"
  embedding_url = "http://embedding:7997"

  # Requests reach the ui, and the ui's requests reach the api, from the
  # environment's own proxies, whose addresses are in this range.
  platform_cidr = "100.100.0.0/16"

  # config.json is too big for a container setting (92 KB), so it travels
  # compressed and is written to /app/config.json when the container starts.
  prepare_and_run = join(" ", [
    "python -c 'import base64, gzip, os;",
    "open(\"/app/config.json\", \"wb\").write(gzip.decompress(base64.b64decode(os.environ[\"EVIDENCELAB_CONFIG_GZ\"])))'",
    "&& exec \"$@\"",
  ])

  app_environment = merge(var.extra_environment, {
    EVIDENCELAB_CONFIG_GZ = base64gzip(file(var.config_json_path))
    QDRANT_HOST           = local.qdrant_url
    POSTGRES_HOST         = azurerm_postgresql_flexible_server.main.fqdn
    POSTGRES_PORT         = "5432"
    POSTGRES_DB           = azurerm_postgresql_flexible_server_database.main.name
    POSTGRES_USER         = azurerm_postgresql_flexible_server.main.administrator_login
    # Azure's Postgres certificates chain to roots in the image's own bundle.
    PGSSLMODE              = "verify-full"
    PGSSLROOTCERT          = "/etc/ssl/certs/ca-certificates.crt"
    EMBEDDING_API_URL      = local.embedding_url
    DATA_MOUNT_PATH        = "/app/data"
    PYTHONPATH             = "/app"
    AZURE_FOUNDRY_ENDPOINT = "https://${azurerm_cognitive_account.models.custom_subdomain_name}.openai.azure.com/"
    USER_MODULE            = var.user_module
    APP_BASE_URL           = local.site_url
    CORS_ALLOWED_ORIGINS   = local.site_url
    AUTH_COOKIE_SECURE     = "true"
  })

  # The secret settings, by setting name. Each becomes a Container Apps
  # secret named after its setting in lower case with hyphens (Container
  # Apps does not allow capitals or underscores), which fills the setting.
  secret_settings = merge(var.provider_secrets, {
    API_SECRET_KEY        = random_password.api_secret_key.result
    AUTH_SECRET_KEY       = random_password.auth_secret_key.result
    KEY_ENCRYPTION_KEY    = replace(replace(random_bytes.key_encryption_key.base64, "+", "-"), "/", "_")
    QDRANT_API_KEY        = local.qdrant_key
    POSTGRES_PASSWORD     = random_password.postgres.result
    RATELIMIT_STORAGE_URL = "rediss://:${azurerm_managed_redis.main.default_database[0].primary_access_key}@${azurerm_managed_redis.main.hostname}:${azurerm_managed_redis.main.default_database[0].port}/0"
    AZURE_FOUNDRY_KEY     = azurerm_cognitive_account.models.primary_access_key
  })
  app_secret_settings = { for k in nonsensitive(keys(local.secret_settings)) : k => lower(replace(k, "_", "-")) }
  app_secrets         = { for k, v in local.secret_settings : local.app_secret_settings[k] => v }

  # The api and mcp apps differ only in command, port, size and settings.
  backend_apps = {
    api = {
      command = ["uvicorn", "ui.backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
      port    = 8000
      size    = var.api
      env = {
        API_ROOT_PATH       = "/api"
        FORWARDED_ALLOW_IPS = local.platform_cidr
      }
    }
    mcp = {
      command = ["python", "-m", "mcp_server.http_server"]
      port    = 8001
      size    = var.mcp
      env     = {}
    }
  }

  jobs = {
    migrate = {
      command = ["alembic", "upgrade", "head"]
      size    = var.migrate_job
      timeout = 1800
    }
    # Always started with its own command by scripts/run-job.sh.
    pipeline = {
      command = ["python", "-m", "pipeline.orchestrator", "--help"]
      size    = var.pipeline_job
      timeout = var.pipeline_timeout_hours * 3600
    }
  }
}

resource "azurerm_container_app" "backend" {
  for_each                     = var.services_enabled ? local.backend_apps : {}
  name                         = each.key
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  dynamic "secret" {
    for_each = local.app_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  ingress {
    transport        = "tcp"
    target_port      = each.value.port
    exposed_port     = each.value.port
    external_enabled = false
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = each.value.size.replicas
    max_replicas = each.value.size.replicas

    container {
      name    = each.key
      image   = local.app_image
      cpu     = each.value.size.cpu
      memory  = each.value.size.memory
      command = ["sh", "-c", local.prepare_and_run, "evidencelab"]
      args    = each.value.command

      dynamic "env" {
        for_each = merge(local.app_environment, each.value.env)
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.app_secret_settings
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      startup_probe {
        transport               = "TCP"
        port                    = each.value.port
        interval_seconds        = 10
        failure_count_threshold = 60
      }

      volume_mounts {
        name = "data"
        path = "/app/data"
      }
    }

    volume {
      name         = "data"
      storage_name = azurerm_container_app_environment_storage.data.name
      storage_type = "AzureFile"
    }
  }
}

resource "azurerm_container_app" "embedding" {
  count                        = var.services_enabled ? 1 : 0
  name                         = "embedding"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  ingress {
    transport        = "tcp"
    target_port      = 7997
    exposed_port     = 7997
    external_enabled = false
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Loading the model takes minutes, so it never scales to zero.
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "embedding"
      image  = var.embedding_image
      cpu    = var.embedding.cpu
      memory = var.embedding.memory
      args   = ["v2"]

      env {
        name  = "INFINITY_MODEL_ID"
        value = var.embedding_model
      }
      env {
        name  = "INFINITY_BATCH_SIZE"
        value = "8"
      }
      env {
        name  = "INFINITY_PORT"
        value = "7997"
      }
      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }

      # Downloading and loading the model can take 10 minutes or more.
      startup_probe {
        transport               = "TCP"
        port                    = 7997
        interval_seconds        = 10
        failure_count_threshold = 180
      }
    }
  }
}

resource "azurerm_container_app" "ui" {
  count                        = var.services_enabled ? 1 : 0
  name                         = "ui"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  # The only app reachable from the internet. Container Apps serves it over
  # HTTPS on the environment's domain, and redirects plain HTTP.
  ingress {
    external_enabled = true
    target_port      = 80
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.ui.replicas
    max_replicas = var.ui.replicas

    container {
      name   = "ui"
      image  = "${azurerm_container_registry.main.login_server}/ui:${var.ui_image_tag}"
      cpu    = var.ui.cpu
      memory = var.ui.memory

      env {
        name  = "API_UPSTREAM"
        value = local.api_url
      }
      env {
        name  = "MCP_UPSTREAM"
        value = local.mcp_url
      }
      env {
        name  = "NGINX_RESOLVER"
        value = local.dns_server
      }
      env {
        name  = "NGINX_REAL_IP_FROM"
        value = local.platform_cidr
      }
    }
  }

  depends_on = [azurerm_role_assignment.registry_pull, azurerm_container_app.backend]
}

resource "azurerm_container_app_job" "this" {
  for_each                     = local.jobs
  name                         = each.key
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = each.value.timeout
  replica_retry_limit          = 0
  tags                         = local.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  dynamic "secret" {
    for_each = local.app_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  template {
    container {
      name    = each.key
      image   = local.app_image
      cpu     = each.value.size.cpu
      memory  = each.value.size.memory
      command = ["sh", "-c", local.prepare_and_run, "evidencelab"]
      args    = each.value.command

      dynamic "env" {
        for_each = local.app_environment
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.app_secret_settings
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      volume_mounts {
        name = "data"
        path = "/app/data"
      }
    }

    volume {
      name         = "data"
      storage_name = azurerm_container_app_environment_storage.data.name
      storage_type = "AzureFile"
    }
  }
}
