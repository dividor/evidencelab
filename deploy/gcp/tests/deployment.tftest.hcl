# Plan-only tests with mocked providers: they check the template's choices
# without a Google Cloud project. Run with: terraform test (in deploy/gcp).

mock_provider "google" {
  mock_data "google_project" {
    defaults = {
      number = "123456789012"
    }
  }
  mock_resource "google_sql_database_instance" {
    # Known while planning, so tests can check the names built from it.
    override_during = plan
    defaults = {
      private_ip_address = "10.1.0.5"
      dns_names = [{
        name            = "abc123.def456.us-central1.sql-psa.goog."
        connection_type = "PRIVATE_SERVICES_ACCESS"
        dns_scope       = "INSTANCE"
      }]
      server_ca_cert = [{ cert = "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n" }]
    }
  }
  mock_resource "google_redis_instance" {
    override_during = plan
    defaults = {
      host            = "10.2.0.3"
      port            = 6378
      auth_string     = "test-auth"
      server_ca_certs = [{ cert = "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n" }]
    }
  }
  mock_resource "google_dns_managed_zone" {
    override_during = plan
    defaults = {
      name = "evidencelab-postgres"
    }
  }
}

mock_provider "random" {
  mock_resource "random_string" {
    override_during = plan
    defaults = {
      result = "abc123"
    }
  }
}

variables {
  project_id          = "example-project"
  evidencelab_version = "1.6.5"
  config_json_path    = "tests/fixtures/minimal-config.json"
}

run "the_first_apply_creates_the_jobs_but_no_services" {
  command = plan

  assert {
    condition     = length(google_cloud_run_v2_service.web) == 0 && length(google_cloud_run_v2_service.embedding) == 0
    error_message = "With services_enabled false, no service should exist yet: the web app image is not pushed."
  }
  assert {
    condition     = toset(keys(google_cloud_run_v2_job.this)) == toset(["migrate", "pipeline"])
    error_message = "The migrate and pipeline jobs should exist from the first apply."
  }
}

run "nginx_reaches_the_api_and_mcp_in_the_same_instance" {
  command = plan

  variables {
    services_enabled = true
  }

  # Cloud Run picks a service by host name and nginx passes on the visitor's,
  # so the api and mcp run beside nginx and it reaches them on localhost.
  assert {
    condition     = [for c in google_cloud_run_v2_service.web[0].template[0].containers : c.name] == ["ui", "api", "mcp"]
    error_message = "The web service should run the ui, api and mcp containers together."
  }
  assert {
    condition = (
      anytrue([for e in google_cloud_run_v2_service.web[0].template[0].containers[0].env : e.name == "API_UPSTREAM" && e.value == "http://127.0.0.1:8000"]) &&
      anytrue([for e in google_cloud_run_v2_service.web[0].template[0].containers[0].env : e.name == "MCP_UPSTREAM" && e.value == "http://127.0.0.1:8001"])
    )
    error_message = "nginx should reach the api and mcp on localhost."
  }
}

run "only_the_web_service_is_public" {
  command = plan

  variables {
    services_enabled = true
  }

  assert {
    condition     = google_cloud_run_v2_service.web[0].ingress == "INGRESS_TRAFFIC_ALL" && google_cloud_run_v2_service.embedding[0].ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    error_message = "Only the web service should be reachable from the internet."
  }
  assert {
    condition     = google_sql_database_instance.main.settings[0].ip_configuration[0].ipv4_enabled == false
    error_message = "Postgres should have no public address."
  }
  assert {
    condition     = length(google_compute_instance.qdrant[0].network_interface[0].access_config) == 0
    error_message = "Qdrant's machine should have no public address."
  }
  assert {
    condition     = google_storage_bucket.data.public_access_prevention == "enforced"
    error_message = "The document bucket must not be public."
  }
}

run "postgres_connections_verify_the_server_certificate" {
  command = plan

  assert {
    condition     = local.app_environment["PGSSLMODE"] == "verify-full" && local.app_environment["PGSSLROOTCERT"] == "/tmp/pg-ca.pem"
    error_message = "Postgres connections should verify the server against Cloud SQL's certificate authority."
  }
  assert {
    condition     = google_sql_database_instance.main.settings[0].ip_configuration[0].ssl_mode == "ENCRYPTED_ONLY"
    error_message = "Cloud SQL should refuse unencrypted connections."
  }
  assert {
    condition     = google_dns_record_set.postgres.name == "abc123.def456.us-central1.sql-psa.goog." && tolist(google_dns_record_set.postgres.rrdatas) == tolist(["10.1.0.5"])
    error_message = "The certificate's name should point at the private address."
  }
  # The certificate's name ends with a dot, and the drivers match it only
  # when the host does too.
  assert {
    condition     = local.app_environment["POSTGRES_HOST"] == "abc123.def456.us-central1.sql-psa.goog."
    error_message = "The containers should connect by the certificate's name, trailing dot included."
  }
}

run "rate_limits_are_shared_through_redis_over_verified_tls" {
  command = plan

  assert {
    condition     = google_redis_instance.main.transit_encryption_mode == "SERVER_AUTHENTICATION" && google_redis_instance.main.auth_enabled
    error_message = "Redis should require TLS and a password."
  }
  assert {
    condition     = nonsensitive(local.secret_settings["RATELIMIT_STORAGE_URL"]) == "rediss://:test-auth@10.2.0.3:6378/0?ssl_ca_certs=/tmp/redis-ca.pem"
    error_message = "The rate limiter should reach Redis over TLS, checking Memorystore's certificate authority."
  }
}

run "the_containers_use_vertex_ai_as_their_service_account" {
  command = plan

  assert {
    condition     = local.app_environment["GOOGLE_CLOUD_PROJECT"] == "example-project" && local.app_environment["GOOGLE_CLOUD_LOCATION"] == "global"
    error_message = "The containers should call Vertex AI in the deployment's project, on the global location the Gemini 3 models are served from."
  }
  assert {
    condition     = toset([for m in google_project_iam_member.run : m.role]) == toset(["roles/aiplatform.user", "roles/discoveryengine.viewer"])
    error_message = "The containers' account should be allowed to call Vertex AI and the Vertex ranker, and nothing else project-wide."
  }
}

run "docker_hub_images_come_through_the_remote_repository" {
  command = plan

  assert {
    condition     = local.app_image == "us-central1-docker.pkg.dev/example-project/evidencelab-dockerhub/astrobagel/evidencelab:1.6.5"
    error_message = "The Evidence Lab image should be pulled through the deployment's Docker Hub repository."
  }
  assert {
    condition     = google_artifact_registry_repository.dockerhub.mode == "REMOTE_REPOSITORY"
    error_message = "The Docker Hub repository should be a remote repository."
  }
}

run "service_addresses_are_known_before_the_services_exist" {
  command = plan

  assert {
    condition     = output.site_url == "https://evidencelab-web-123456789012.us-central1.run.app"
    error_message = "The site should be the web service's run.app address."
  }
  assert {
    condition     = local.app_environment["EMBEDDING_API_URL"] == "https://evidencelab-embedding-123456789012.us-central1.run.app"
    error_message = "The jobs should know the embedding service's address on the first apply."
  }
}

run "secrets_come_from_secret_manager" {
  command = plan

  variables {
    provider_secrets = { EXAMPLE_PROVIDER_SETTING = "example-value" }
  }

  assert {
    condition     = local.secret_ids["EXAMPLE_PROVIDER_SETTING"] == "evidencelab-example-provider-setting" && local.secret_ids["POSTGRES_PASSWORD"] == "evidencelab-postgres-password"
    error_message = "Each secret setting should have a Secret Manager secret named after it."
  }
}

run "the_cloud_sql_name_carries_the_suffix" {
  command = plan

  assert {
    condition     = google_sql_database_instance.main.name == "evidencelab-abc123"
    error_message = "A deleted Cloud SQL name stays taken for a week, so each deployment adds its suffix."
  }
}

run "test_settings_drop_the_standbys" {
  command = plan

  variables {
    db_high_availability = false
    redis_tier           = "BASIC"
  }

  assert {
    condition     = google_sql_database_instance.main.settings[0].availability_type == "ZONAL" && google_redis_instance.main.tier == "BASIC"
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
