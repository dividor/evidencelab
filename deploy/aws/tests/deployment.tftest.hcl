# Plan-only tests with mocked providers: they check the template's choices
# without an AWS account. Run with: terraform test (in deploy/aws).

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-2a", "us-east-2b", "us-east-2c"]
    }
  }
  mock_data "aws_rds_engine_version" {
    defaults = {
      version_actual = "16.13"
    }
  }
  mock_data "aws_ssm_parameter" {
    defaults = {
      value = "ami-0123456789abcdef0"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = {
      arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:evidencelab-app"
    }
  }
  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/evidencelab-ecs-execution"
    }
  }
  mock_resource "aws_lb" {
    defaults = {
      dns_name = "evidencelab-123.us-east-2.elb.amazonaws.com"
    }
  }
  mock_resource "aws_ecr_repository" {
    defaults = {
      repository_url = "123456789012.dkr.ecr.us-east-2.amazonaws.com/evidencelab/ui"
    }
  }
}

mock_provider "random" {}

mock_provider "http" {
  mock_data "http" {
    defaults = {
      response_body = "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n"
    }
  }
}

variables {
  evidencelab_version = "1.6.5"
  config_json_path    = "tests/fixtures/minimal-config.json"
}

run "without_a_domain_serves_plain_http_on_the_load_balancer" {
  command = plan

  assert {
    condition     = aws_lb_listener.http.default_action[0].type == "forward"
    error_message = "Without a domain, port 80 should serve the site."
  }
  assert {
    condition     = length(aws_lb_listener.https) == 0 && length(aws_acm_certificate.site) == 0
    error_message = "Without a domain there should be no certificate or HTTPS listener."
  }
  assert {
    condition     = local.app_environment["AUTH_COOKIE_SECURE"] == "false"
    error_message = "Sign-in cookies cannot be Secure over plain HTTP."
  }
}

run "with_a_domain_serves_https_and_redirects_http" {
  command = plan

  variables {
    domain_name     = "evidencelab.example.org"
    route53_zone_id = "Z0123456789"
  }

  assert {
    condition     = aws_lb_listener.http.default_action[0].type == "redirect"
    error_message = "With a domain, port 80 should redirect to HTTPS."
  }
  assert {
    condition     = length(aws_lb_listener.https) == 1 && length(aws_route53_record.site) == 1
    error_message = "With a domain there should be an HTTPS listener and a DNS record."
  }
  assert {
    condition     = local.site_url == "https://evidencelab.example.org"
    error_message = "The site address should be the HTTPS domain."
  }
  assert {
    condition     = local.app_environment["AUTH_COOKIE_SECURE"] == "true"
    error_message = "Sign-in cookies should be Secure over HTTPS."
  }
}

run "without_a_qdrant_url_runs_qdrant_on_ec2" {
  command = plan

  assert {
    condition     = length(aws_instance.qdrant) == 1
    error_message = "Qdrant should run on EC2 when no URL is given."
  }
}

run "with_a_qdrant_url_uses_it_and_creates_no_instance" {
  command = plan

  variables {
    qdrant_url = "https://cluster.us-east-2-0.aws.cloud.qdrant.io:6333"
  }

  assert {
    condition     = length(aws_instance.qdrant) == 0
    error_message = "No Qdrant instance should be created when a URL is given."
  }
  assert {
    condition     = local.app_environment["QDRANT_HOST"] == "https://cluster.us-east-2-0.aws.cloud.qdrant.io:6333"
    error_message = "The containers should use the given Qdrant URL."
  }
}

run "services_stay_at_zero_until_enabled" {
  command = plan

  assert {
    condition     = aws_ecs_service.backend["api"].desired_count == 0 && aws_ecs_service.ui.desired_count == 0
    error_message = "Services should not start before services_enabled is set."
  }
}

run "enabled_services_run_their_configured_copies" {
  command = plan

  variables {
    services_enabled = true
    api              = { cpu = 2048, memory = 8192, count = 3 }
  }

  assert {
    condition     = aws_ecs_service.backend["api"].desired_count == 3
    error_message = "The api should run the configured number of copies."
  }
  assert {
    condition     = aws_ecs_service.backend["embedding"].desired_count == 1
    error_message = "One embedding copy should always run."
  }
}

run "containers_get_the_load_balancer_settings" {
  command = plan

  assert {
    condition     = local.app_environment["PGSSLMODE"] == "verify-full"
    error_message = "Postgres connections should verify the server certificate."
  }
  assert {
    condition     = startswith(local.app_environment["RATELIMIT_STORAGE_URL"], "rediss://")
    error_message = "Rate-limit counts should be shared through Redis over TLS."
  }
  assert {
    condition     = local.app_containers["api"].env["FORWARDED_ALLOW_IPS"] == "10.0.0.0/16"
    error_message = "The api should trust nginx in the VPC for the visitor's address."
  }
  assert {
    condition     = local.app_environment["EVIDENCELAB_CONFIG_GZ"] == base64gzip(file("tests/fixtures/minimal-config.json"))
    error_message = "config.json should travel compressed to the containers."
  }
}

run "sign_in_off_is_refused" {
  command = plan

  variables {
    user_module = "off"
  }

  expect_failures = [var.user_module]
}

run "provider_key_names_reach_the_containers_as_secrets" {
  command = plan

  variables {
    provider_secret_names = ["AZURE_FOUNDRY_KEY", "AZURE_FOUNDRY_ENDPOINT"]
  }

  assert {
    condition = alltrue([
      for n in ["AZURE_FOUNDRY_KEY", "AZURE_FOUNDRY_ENDPOINT", "API_SECRET_KEY", "POSTGRES_PASSWORD"] :
      contains([for s in local.app_secrets_refs : s.name], n)
    ])
    error_message = "Provider keys, app keys and the database password should all reach the containers as secrets."
  }
  assert {
    condition     = !contains(keys(local.app_environment), "AZURE_FOUNDRY_KEY")
    error_message = "Provider keys must not be plain container settings."
  }
}

run "anonymous_access_is_off_unless_asked_for" {
  command = plan

  assert {
    condition     = output.anonymous_access == false
    error_message = "The web app should not carry the API key unless anonymous_access is set."
  }
}
