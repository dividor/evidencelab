# Plan-only tests with mocked providers: they check the template's choices
# without an Azure subscription. Run with: terraform test (in deploy/azure).

mock_provider "azurerm" {
  mock_resource "azurerm_container_app_environment" {
    override_during = plan
    defaults = {
      id             = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/evidencelab/providers/Microsoft.App/managedEnvironments/evidencelab"
      default_domain = "example-1234.eastus2.azurecontainerapps.io"
    }
  }
  mock_resource "azurerm_cognitive_account" {
    # Known while planning, so tests can check the endpoint built from it.
    override_during = plan
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/evidencelab/providers/Microsoft.CognitiveServices/accounts/evidencelab-abc123"
      custom_subdomain_name = "evidencelab-abc123"
    }
  }
  mock_resource "azurerm_managed_redis" {
    override_during = plan
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/evidencelab/providers/Microsoft.Cache/redisEnterprise/evidencelab-abc123"
      hostname = "evidencelab-abc123.eastus2.redis.azure.net"
      default_database = {
        port               = 10000
        primary_access_key = "test-key"
      }
    }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      login_server = "evidencelababc123.azurecr.io"
    }
  }
}

mock_provider "random" {
  mock_resource "random_string" {
    # Known while planning, so the names built from it are too.
    override_during = plan
    defaults = {
      result = "abc123"
    }
  }
}

mock_provider "tls" {}

variables {
  subscription_id     = "00000000-0000-0000-0000-000000000000"
  evidencelab_version = "1.6.5"
  config_json_path    = "tests/fixtures/minimal-config.json"
}

run "the_first_apply_creates_the_jobs_but_no_apps" {
  command = plan

  assert {
    condition     = length(azurerm_container_app.backend) == 0 && length(azurerm_container_app.ui) == 0 && length(azurerm_container_app.embedding) == 0
    error_message = "With services_enabled false, no app should exist yet: the web app image is not pushed."
  }
  assert {
    condition     = toset(keys(azurerm_container_app_job.this)) == toset(["migrate", "pipeline"])
    error_message = "The migrate and pipeline jobs should exist from the first apply."
  }
}

run "only_the_ui_is_reachable_from_the_internet" {
  command = plan

  variables {
    services_enabled = true
  }

  assert {
    condition     = azurerm_container_app.ui[0].ingress[0].external_enabled
    error_message = "The ui should be reachable from the internet."
  }
  assert {
    condition     = alltrue([for app in azurerm_container_app.backend : !app.ingress[0].external_enabled]) && !azurerm_container_app.embedding[0].ingress[0].external_enabled
    error_message = "The api, mcp and embedding apps must be internal."
  }
  assert {
    condition     = azurerm_postgresql_flexible_server.main.public_network_access_enabled == false && azurerm_managed_redis.main.public_network_access == "Disabled"
    error_message = "Postgres and Redis must only be reachable inside the network."
  }
  assert {
    condition     = one(azurerm_storage_account.data.network_rules).default_action == "Deny"
    error_message = "The file share should refuse connections from outside the apps' subnet."
  }
}

run "the_ui_reaches_the_backend_apps_over_tcp" {
  command = plan

  variables {
    services_enabled = true
  }

  # The environment's HTTP routing picks the app by Host header, and nginx
  # passes on the visitor's, so the backend apps must take plain TCP.
  assert {
    condition     = alltrue([for app in azurerm_container_app.backend : app.ingress[0].transport == "tcp"]) && azurerm_container_app.embedding[0].ingress[0].transport == "tcp"
    error_message = "The api, mcp and embedding apps should take plain TCP."
  }
  assert {
    condition     = azurerm_container_app.backend["api"].ingress[0].exposed_port == 8000 && azurerm_container_app.backend["mcp"].ingress[0].exposed_port == 8001
    error_message = "The api and mcp apps should listen on their compose ports."
  }
  assert {
    condition = (
      anytrue([for e in azurerm_container_app.ui[0].template[0].container[0].env : e.name == "API_UPSTREAM" && e.value == "http://api.k8se-apps.svc.cluster.local:8000"]) &&
      anytrue([for e in azurerm_container_app.ui[0].template[0].container[0].env : e.name == "MCP_UPSTREAM" && e.value == "http://mcp.k8se-apps.svc.cluster.local:8001"])
    )
    error_message = "The ui should reach the api and mcp apps by their full names: nginx does not use search domains."
  }
  assert {
    condition = (
      anytrue([for e in azurerm_container_app.ui[0].template[0].container[0].env : e.name == "NGINX_REAL_IP_FROM" && e.value == "100.100.0.0/16"]) &&
      anytrue([for e in azurerm_container_app.backend["api"].template[0].container[0].env : e.name == "FORWARDED_ALLOW_IPS" && e.value == "100.100.0.0/16"])
    )
    error_message = "nginx and the api should take the visitor's address from the environment's proxies."
  }
}

run "the_site_is_served_over_https_on_the_environment_domain" {
  command = plan

  assert {
    condition     = output.site_url == "https://ui.example-1234.eastus2.azurecontainerapps.io"
    error_message = "The site should be the ui app's HTTPS address."
  }
  assert {
    condition     = local.app_environment["AUTH_COOKIE_SECURE"] == "true" && local.app_environment["APP_BASE_URL"] == output.site_url
    error_message = "Sign-in cookies should be Secure, and the api should know the site's address."
  }
}

run "postgres_connections_verify_the_server_certificate" {
  command = plan

  assert {
    condition     = local.app_environment["PGSSLMODE"] == "verify-full" && local.app_environment["PGSSLROOTCERT"] == "/etc/ssl/certs/ca-certificates.crt"
    error_message = "Postgres connections should verify the server against the image's certificate bundle."
  }
  assert {
    condition     = azurerm_postgresql_flexible_server_configuration.extensions.value == "VECTOR,PG_TRGM"
    error_message = "Azure must allow the extensions the migrations create."
  }
}

run "rate_limits_are_shared_through_redis_over_tls" {
  command = plan

  assert {
    condition     = startswith(nonsensitive(local.app_secrets["ratelimit-storage-url"]), "rediss://")
    error_message = "The rate limiter should reach Redis over TLS."
  }
  assert {
    condition     = one(azurerm_managed_redis.main.default_database).clustering_policy == "NoCluster"
    error_message = "The rate limiter's Redis client does not follow cluster redirects."
  }
  assert {
    condition     = local.app_secret_settings["RATELIMIT_STORAGE_URL"] == "ratelimit-storage-url"
    error_message = "The Redis address carries its key, so it must come from a secret."
  }
}

run "the_containers_use_the_deployments_own_foundry_models" {
  command = plan

  assert {
    condition     = local.app_environment["AZURE_FOUNDRY_ENDPOINT"] == "https://evidencelab-abc123.openai.azure.com/"
    error_message = "The containers should call the deployment's own Foundry resource."
  }
  assert {
    condition     = toset(keys(azurerm_cognitive_deployment.this)) == toset(["text-embedding-3-small", "gpt-4.1-mini", "Cohere-rerank-v4.0-fast"])
    error_message = "The models in config.json's Azure Foundry set should be deployed."
  }
}

run "qdrant_runs_on_a_virtual_machine_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_linux_virtual_machine.qdrant) == 1
    error_message = "Without qdrant_url, Qdrant should run on its own virtual machine."
  }
}

run "an_existing_qdrant_replaces_the_virtual_machine" {
  command = plan

  variables {
    qdrant_url = "https://example.cloud.qdrant.io:6333"
  }

  assert {
    condition     = length(azurerm_linux_virtual_machine.qdrant) == 0 && local.app_environment["QDRANT_HOST"] == "https://example.cloud.qdrant.io:6333"
    error_message = "With qdrant_url, the containers should use it and no virtual machine should be created."
  }
}

run "provider_keys_become_secrets" {
  command = plan

  variables {
    services_enabled = true
    provider_secrets = { EXAMPLE_PROVIDER_SETTING = "example-value" }
  }

  assert {
    condition     = nonsensitive(local.app_secrets["example-provider-setting"]) == "example-value" && local.app_secret_settings["EXAMPLE_PROVIDER_SETTING"] == "example-provider-setting"
    error_message = "Each provider key should become a secret named after its setting."
  }
}

run "high_availability_can_be_turned_off_for_tests" {
  command = plan

  variables {
    db_high_availability    = false
    redis_high_availability = false
  }

  assert {
    condition     = length(azurerm_postgresql_flexible_server.main.high_availability) == 0 && azurerm_managed_redis.main.high_availability_enabled == false
    error_message = "Turning high availability off should drop the standbys."
  }
}

run "a_name_that_cannot_name_the_resources_is_refused" {
  command = plan

  variables {
    name = "Evidence_Lab"
  }

  expect_failures = [var.name]
}
