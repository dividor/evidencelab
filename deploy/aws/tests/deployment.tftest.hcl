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
      version_actual = "17.9"
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
    # Known while planning, so tests can compare role ARNs.
    override_during = plan
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
  mock_data "aws_ec2_managed_prefix_list" {
    defaults = {
      id = "pl-3b927c52"
    }
  }
  mock_resource "aws_s3_bucket" {
    # Known while planning, so tests can follow the bucket into the task.
    override_during = plan
    defaults = {
      bucket = "evidencelab-pipeline-files-20261120"
      arn    = "arn:aws:s3:::evidencelab-pipeline-files-20261120"
    }
  }
  mock_resource "aws_cloudfront_distribution" {
    # Known while planning, so tests can check the site address.
    override_during = plan
    defaults = {
      domain_name    = "d111111abcdef8.cloudfront.net"
      hosted_zone_id = "Z2FDTNDATAQYW2"
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

# terraform test also reads deploy/aws/terraform.tfvars, so a deployment's own
# settings would leak into the tests. Every value a run below relies on is set
# here, and these take precedence over terraform.tfvars.
variables {
  evidencelab_version   = "1.6.5"
  config_json_path      = "tests/fixtures/minimal-config.json"
  region                = "us-east-2"
  domain_name           = ""
  route53_zone_id       = ""
  qdrant_url            = ""
  services_enabled      = false
  user_module           = "on_passive"
  anonymous_access      = false
  provider_secret_names = []
  api                   = { cpu = 2048, memory = 8192, count = 2 }

  cloudfront_enabled             = false
  cloudfront_price_class         = "PriceClass_100"
  cloudfront_origin_read_timeout = 60
  waf_allowed_ip_ranges          = []
  waf_rate_limit                 = 2000
  # null takes the template's default (the variable is not nullable), so the
  # runs check the default itself and terraform.tfvars cannot change it.
  waf_core_rules_to_count = null
  waf_count_only          = false

  pipeline_files_dir   = ""
  customize_assets_dir = ""

  backups_enabled       = true
  backup_schedule       = "cron(0 3 ? * SUN *)"
  backup_retention_days = 35

  transfer_retention_days = 30
  db_engine_version       = "17"
  restore_task            = { cpu = 1024, memory = 4096 }

  # null takes the defaults: no alerts, the Bedrock call log on for a year.
  alert_emails                    = null
  bedrock_alarms                  = null
  bedrock_call_log                = null
  bedrock_call_log_retention_days = null
  extra_environment               = {}
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
    condition     = local.app_environment["OAUTH_CALLBACK_BASE_URL"] == "https://evidencelab.example.org/api"
    error_message = "Google and Microsoft sign-in should return visitors to the site's /api, not localhost."
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

run "containers_can_call_bedrock_in_their_region" {
  command = plan

  variables {
    config_json_path = "tests/fixtures/bedrock-config.json"
  }

  assert {
    condition     = local.app_environment["AWS_REGION"] == "us-east-2"
    error_message = "The containers should be told the deployment's region."
  }
  assert {
    condition     = aws_ecs_task_definition.app["api"].task_role_arn == aws_iam_role.task.arn
    error_message = "The api should run as the task role that may call Bedrock."
  }
  assert {
    condition     = length(aws_iam_role_policy.bedrock) == 1 && aws_iam_role_policy.bedrock[0].role == aws_iam_role.task.id
    error_message = "The task role should get the Bedrock policy."
  }
}

run "only_the_bedrock_models_config_json_lists_may_be_called" {
  command = plan

  variables {
    config_json_path = "tests/fixtures/bedrock-config.json"
  }

  assert {
    condition = local.bedrock_model_ids == sort([
      "amazon.rerank-v1:0",
      "amazon.titan-embed-text-v2:0",
      "us.amazon.nova-2-lite-v1:0",
      "mistral.mistral-large-2402-v1:0",
    ])
    error_message = "The role should get exactly the config's Bedrock models, and nothing from other providers."
  }
  assert {
    condition     = local.bedrock_profile_arns == tolist(["arn:aws:bedrock:us-east-2:${data.aws_caller_identity.current.account_id}:inference-profile/us.amazon.nova-2-lite-v1:0"])
    error_message = "An inference profile should be allowed in the deployment's region only, where the app calls it."
  }
  assert {
    condition = local.bedrock_direct_model_arns == sort([
      "arn:aws:bedrock:us-west-2::foundation-model/amazon.rerank-v1:0",
      "arn:aws:bedrock:us-east-2::foundation-model/amazon.titan-embed-text-v2:0",
      "arn:aws:bedrock:us-east-2::foundation-model/mistral.mistral-large-2402-v1:0",
    ])
    error_message = "Models called directly should be allowed only in the region the app calls them in: chat and embedding models in the deployment's, rerank in its own."
  }
  assert {
    condition     = local.bedrock_routed_model_arns == tolist(["arn:aws:bedrock:*::foundation-model/amazon.nova-2-lite-v1:0"])
    error_message = "A profile's base model should be allowed in every region it may route to."
  }
}

run "the_bedrock_policy_works_only_from_the_nat_gateway_address" {
  command = plan

  variables {
    config_json_path = "tests/fixtures/bedrock-config.json"
  }

  # The NAT gateway's address, known while planning.
  override_resource {
    target          = aws_eip.nat
    override_during = plan
    values = {
      public_ip = "203.0.113.10"
    }
  }

  assert {
    condition = (
      data.aws_iam_policy_document.bedrock[0].statement[0].sid == "FromTheDeploymentOnly"
      && sort(tolist(data.aws_iam_policy_document.bedrock[0].statement[0].resources)) == sort(concat(local.bedrock_profile_arns, local.bedrock_direct_model_arns))
      && sort(tolist(data.aws_iam_policy_document.bedrock[0].statement[0].actions)) == tolist(["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"])
    )
    error_message = "The profiles and the models called directly should share one statement."
  }
  assert {
    condition = (
      length(data.aws_iam_policy_document.bedrock[0].statement[0].condition) == 1
      && one(data.aws_iam_policy_document.bedrock[0].statement[0].condition).test == "IpAddress"
      && one(data.aws_iam_policy_document.bedrock[0].statement[0].condition).variable == "aws:SourceIp"
      && tolist(one(data.aws_iam_policy_document.bedrock[0].statement[0].condition).values) == tolist(["203.0.113.10/32"])
    )
    error_message = "They should be allowed only from the NAT gateway's address, which every container's calls come from."
  }
}

run "base_models_behind_a_profile_are_allowed_only_through_it" {
  command = plan

  variables {
    config_json_path = "tests/fixtures/bedrock-config.json"
  }

  assert {
    condition = (
      data.aws_iam_policy_document.bedrock[0].statement[1].sid == "ThroughTheProfilesOnly"
      && tolist(data.aws_iam_policy_document.bedrock[0].statement[1].resources) == local.bedrock_routed_model_arns
      && one(data.aws_iam_policy_document.bedrock[0].statement[1].condition).test == "StringLike"
      && one(data.aws_iam_policy_document.bedrock[0].statement[1].condition).variable == "bedrock:InferenceProfileArn"
      && tolist(one(data.aws_iam_policy_document.bedrock[0].statement[1].condition).values) == local.bedrock_profile_arns
    )
    error_message = "A profile's base model should be callable only through one of the config's profiles, so it can't be called directly in a region nobody watches."
  }
}

run "a_config_without_a_profile_has_no_profile_statement" {
  command = plan

  variables {
    config_json_path = "tests/fixtures/bedrock-direct-config.json"
  }

  assert {
    condition     = length(data.aws_iam_policy_document.bedrock[0].statement) == 1 && length(local.bedrock_routed_model_arns) == 0
    error_message = "With no inference profile, only the address-limited statement should be made."
  }
}

run "a_config_without_bedrock_models_gets_no_bedrock_permission" {
  command = plan

  assert {
    condition     = length(local.bedrock_model_ids) == 0 && length(aws_iam_role_policy.bedrock) == 0
    error_message = "With no Bedrock model in config.json the task role should get no Bedrock permission."
  }
}

# --- Alerts -----------------------------------------------------------------

run "without_alert_emails_there_is_no_topic_and_no_alarm" {
  command = plan

  assert {
    condition     = length(aws_sns_topic.alerts) == 0 && length(aws_sns_topic_subscription.alerts) == 0 && length(aws_cloudwatch_metric_alarm.bedrock) == 0
    error_message = "By default no alert topic, subscription or alarm should be made."
  }
}

run "alert_emails_are_subscribed_to_a_topic_in_the_deployment_region" {
  command = plan

  variables {
    alert_emails = ["ops@example.org", "lead@example.org"]
  }

  assert {
    condition     = length(aws_sns_topic.alerts) == 1 && aws_sns_topic.alerts["us-east-2"].name == "evidencelab-alerts" && aws_sns_topic.alerts["us-east-2"].region == "us-east-2"
    error_message = "Alert addresses should get one topic, in the deployment's region."
  }
  assert {
    condition = (
      length(aws_sns_topic_subscription.alerts) == 2
      && alltrue([for s in values(aws_sns_topic_subscription.alerts) : s.protocol == "email" && s.region == "us-east-2"])
      && sort([for s in values(aws_sns_topic_subscription.alerts) : s.endpoint]) == tolist(["lead@example.org", "ops@example.org"])
    )
    error_message = "Each address should be subscribed by email."
  }
}

run "bedrock_alarms_watch_each_model_and_level_in_its_region" {
  command = plan

  variables {
    alert_emails = ["ops@example.org"]
    bedrock_alarms = {
      "us.amazon.nova-2-lite-v1:0" = { input_tokens_per_hour = 2000000, output_tokens_per_hour = 300000 }
      "amazon.rerank-v1:0"         = { region = "us-west-2", invocations_per_hour = 5000 }
    }
  }

  assert {
    condition     = sort(keys(aws_sns_topic.alerts)) == tolist(["us-east-2", "us-west-2"])
    error_message = "An alarm in another region should get a topic there too."
  }
  assert {
    condition     = length(aws_sns_topic_subscription.alerts) == 2
    error_message = "The address should be subscribed to the topic in each region."
  }
  assert {
    condition = sort(keys(aws_cloudwatch_metric_alarm.bedrock)) == sort([
      "us.amazon.nova-2-lite-v1:0 input tokens",
      "us.amazon.nova-2-lite-v1:0 output tokens",
      "amazon.rerank-v1:0 requests",
    ])
    error_message = "There should be one alarm per model and level set, and none for levels left out."
  }
  assert {
    condition = (
      aws_cloudwatch_metric_alarm.bedrock["us.amazon.nova-2-lite-v1:0 output tokens"].metric_name == "OutputTokenCount"
      && aws_cloudwatch_metric_alarm.bedrock["us.amazon.nova-2-lite-v1:0 output tokens"].namespace == "AWS/Bedrock"
      && aws_cloudwatch_metric_alarm.bedrock["us.amazon.nova-2-lite-v1:0 output tokens"].dimensions == tomap({ ModelId = "us.amazon.nova-2-lite-v1:0" })
      && aws_cloudwatch_metric_alarm.bedrock["us.amazon.nova-2-lite-v1:0 output tokens"].statistic == "Sum"
      && aws_cloudwatch_metric_alarm.bedrock["us.amazon.nova-2-lite-v1:0 output tokens"].period == 3600
      && aws_cloudwatch_metric_alarm.bedrock["us.amazon.nova-2-lite-v1:0 output tokens"].threshold == 300000
      && aws_cloudwatch_metric_alarm.bedrock["us.amazon.nova-2-lite-v1:0 output tokens"].region == "us-east-2"
    )
    error_message = "A token alarm should sum the model's output tokens over an hour against its level, in the deployment's region."
  }
  assert {
    condition = (
      aws_cloudwatch_metric_alarm.bedrock["amazon.rerank-v1:0 requests"].metric_name == "Invocations"
      && aws_cloudwatch_metric_alarm.bedrock["amazon.rerank-v1:0 requests"].region == "us-west-2"
      && aws_cloudwatch_metric_alarm.bedrock["amazon.rerank-v1:0 requests"].treat_missing_data == "notBreaching"
    )
    error_message = "A requests alarm should count invocations in the model's own region, and quiet hours should be normal."
  }
}

run "the_daily_ai_limit_emails_when_it_is_reached" {
  command = plan

  variables {
    alert_emails      = ["ops@example.org"]
    extra_environment = { AI_DAILY_COST_LIMIT_USD = "25" }
  }

  assert {
    condition = (
      sort(keys(aws_cloudwatch_log_metric_filter.ai_daily_limit)) == tolist(["api", "mcp"])
      && aws_cloudwatch_log_metric_filter.ai_daily_limit["api"].log_group_name == "/ecs/evidencelab/api"
      && aws_cloudwatch_log_metric_filter.ai_daily_limit["mcp"].log_group_name == "/ecs/evidencelab/mcp"
      && aws_cloudwatch_log_metric_filter.ai_daily_limit["api"].pattern == "\"AI daily limit reached\""
    )
    error_message = "The api and mcp logs should be watched for the line the daily AI limit writes."
  }
  assert {
    condition = (
      length(aws_cloudwatch_metric_alarm.ai_daily_limit) == 1
      && aws_cloudwatch_metric_alarm.ai_daily_limit[0].metric_name == "AiDailyLimitReached"
      && aws_cloudwatch_metric_alarm.ai_daily_limit[0].namespace == "EvidenceLab/evidencelab"
      && aws_cloudwatch_metric_alarm.ai_daily_limit[0].threshold == 0
    )
    error_message = "One alarm should fire on the first such line."
  }
}

run "without_a_daily_ai_limit_there_is_no_limit_alarm" {
  command = plan

  variables {
    alert_emails = ["ops@example.org"]
  }

  assert {
    condition     = length(aws_cloudwatch_log_metric_filter.ai_daily_limit) == 0 && length(aws_cloudwatch_metric_alarm.ai_daily_limit) == 0
    error_message = "No limit set, so nothing to watch for."
  }
}

run "a_daily_ai_limit_without_alert_emails_has_no_alarm" {
  command = plan

  variables {
    extra_environment = { AI_DAILY_COST_LIMIT_USD = "25" }
  }

  assert {
    condition     = length(aws_cloudwatch_metric_alarm.ai_daily_limit) == 0
    error_message = "With no one to tell, no alarm should be made; the limit itself still applies."
  }
}

run "bedrock_alarms_without_alert_emails_are_refused" {
  command = plan

  variables {
    bedrock_alarms = { "amazon.titan-embed-text-v2:0" = { input_tokens_per_hour = 1000 } }
  }

  expect_failures = [var.bedrock_alarms]
}

run "a_bedrock_alarm_without_a_level_is_refused" {
  command = plan

  variables {
    alert_emails   = ["ops@example.org"]
    bedrock_alarms = { "amazon.titan-embed-text-v2:0" = { region = "us-west-2" } }
  }

  expect_failures = [var.bedrock_alarms]
}

run "an_alert_email_that_is_not_an_address_is_refused" {
  command = plan

  variables {
    alert_emails = ["ops-team"]
  }

  expect_failures = [var.alert_emails]
}

# --- CloudFront and AWS WAF --------------------------------------------------

# --- Bedrock call log -------------------------------------------------------

run "the_bedrock_call_log_is_on_in_each_region_the_app_calls_without_text" {
  command = plan

  variables {
    config_json_path = "tests/fixtures/bedrock-config.json"
  }

  assert {
    condition     = sort(keys(aws_bedrock_model_invocation_logging_configuration.this)) == tolist(["us-east-2", "us-west-2"])
    error_message = "The call log should be on in the deployment's region and in the rerank model's."
  }
  assert {
    condition = alltrue([
      for r, c in aws_bedrock_model_invocation_logging_configuration.this : (
        c.region == r
        && c.logging_config[0].text_data_delivery_enabled == false
        && c.logging_config[0].image_data_delivery_enabled == false
        && c.logging_config[0].embedding_data_delivery_enabled == false
        && c.logging_config[0].video_data_delivery_enabled == false
        && c.logging_config[0].cloudwatch_config[0].log_group_name == "/aws/bedrock/evidencelab/model-invocations"
      )
    ])
    error_message = "Each region's log should hold who called which model and its token counts, never the text, images, embeddings or video."
  }
  assert {
    condition     = alltrue([for g in aws_cloudwatch_log_group.bedrock_calls : g.retention_in_days == 365])
    error_message = "By default the call log should be kept for a year."
  }
  assert {
    condition = (
      one(one(data.aws_iam_policy_document.bedrock_logging_assume[0].statement).principals).identifiers == toset(["bedrock.amazonaws.com"])
      && length(one(data.aws_iam_policy_document.bedrock_logging_assume[0].statement).condition) == 2
    )
    error_message = "Only Bedrock, for this account, should be able to write the log."
  }
}

run "the_bedrock_call_log_can_be_turned_off" {
  command = plan

  variables {
    config_json_path = "tests/fixtures/bedrock-config.json"
    bedrock_call_log = false
  }

  assert {
    condition     = length(aws_bedrock_model_invocation_logging_configuration.this) == 0 && length(aws_iam_role.bedrock_logging) == 0
    error_message = "With the call log off nothing should be made."
  }
}

run "a_config_without_bedrock_models_has_no_call_log" {
  command = plan

  assert {
    condition     = length(aws_bedrock_model_invocation_logging_configuration.this) == 0 && length(aws_cloudwatch_log_group.bedrock_calls) == 0
    error_message = "With no Bedrock model there is nothing to log."
  }
}

run "a_call_log_retention_cloudwatch_does_not_offer_is_refused" {
  command = plan

  variables {
    bedrock_call_log_retention_days = 10
  }

  expect_failures = [var.bedrock_call_log_retention_days]
}

run "without_cloudfront_the_load_balancer_is_public_and_no_cloudfront_is_made" {
  command = plan

  assert {
    condition     = aws_lb.main.internal == false && aws_vpc_security_group_ingress_rule.alb_http.cidr_ipv4 == "0.0.0.0/0"
    error_message = "Without CloudFront the load balancer should be the public entry point."
  }
  assert {
    condition     = length(aws_cloudfront_distribution.site) == 0 && length(aws_wafv2_web_acl.site) == 0 && length(aws_cloudfront_vpc_origin.alb) == 0
    error_message = "Without CloudFront there should be no distribution, VPC origin or web ACL."
  }
}

run "without_cloudfront_the_load_balancer_adds_the_visitors_address" {
  command = plan

  assert {
    condition     = aws_lb.main.xff_header_processing_mode == "append"
    error_message = "Without CloudFront the load balancer should add the address that connected to it to X-Forwarded-For."
  }
}

run "with_cloudfront_the_visitors_address_is_the_one_cloudfront_adds" {
  command = plan

  variables {
    cloudfront_enabled = true
  }

  assert {
    condition     = aws_lb.main.xff_header_processing_mode == "preserve"
    error_message = "Behind CloudFront the load balancer should pass X-Forwarded-For on unchanged, so its last entry is the visitor's address CloudFront added, not CloudFront's own."
  }
  assert {
    condition     = one([for e in local.ui_environment : e.value if e.name == "NGINX_REAL_IP_FROM"]) == "10.0.0.0/16"
    error_message = "nginx should trust X-Forwarded-For only from the load balancer in the VPC."
  }
  assert {
    condition     = local.app_containers["api"].env["FORWARDED_ALLOW_IPS"] == "10.0.0.0/16"
    error_message = "The api should trust X-Forwarded-For only from nginx in the VPC."
  }
}

run "with_cloudfront_only_cloudfront_reaches_the_load_balancer" {
  command = plan

  variables {
    cloudfront_enabled = true
  }

  assert {
    condition     = aws_lb.main.internal == true
    error_message = "With CloudFront the load balancer should have no internet address."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_http.prefix_list_id == "pl-3b927c52" && aws_vpc_security_group_ingress_rule.alb_http.cidr_ipv4 == null
    error_message = "The load balancer should accept only CloudFront's origin-facing servers."
  }
  assert {
    condition     = length(aws_lb_listener.https) == 0 && length(aws_vpc_security_group_ingress_rule.alb_https) == 0
    error_message = "CloudFront serves HTTPS; the load balancer should not."
  }
  assert {
    condition     = one(one(aws_cloudfront_distribution.site[0].origin).vpc_origin_config).origin_read_timeout == 60
    error_message = "CloudFront should reach the load balancer through the VPC origin, waiting cloudfront_origin_read_timeout seconds."
  }
}

run "with_cloudfront_the_site_is_https_on_its_cloudfront_address" {
  command = plan

  variables {
    cloudfront_enabled = true
  }

  assert {
    condition     = local.site_url == "https://d111111abcdef8.cloudfront.net"
    error_message = "Without a domain the site address should be CloudFront's own HTTPS address."
  }
  assert {
    condition     = local.app_environment["AUTH_COOKIE_SECURE"] == "true" && local.app_environment["OAUTH_CALLBACK_BASE_URL"] == "https://d111111abcdef8.cloudfront.net/api"
    error_message = "Sign-in cookies should be Secure, and sign-in should return visitors to CloudFront's address."
  }
  assert {
    condition     = local.app_environment["CORS_ALLOWED_ORIGINS"] == "https://d111111abcdef8.cloudfront.net"
    error_message = "The api should accept browser requests from the CloudFront address."
  }
  assert {
    condition     = one(aws_cloudfront_distribution.site[0].default_cache_behavior).viewer_protocol_policy == "redirect-to-https" && one(aws_cloudfront_distribution.site[0].viewer_certificate).cloudfront_default_certificate == true
    error_message = "CloudFront should redirect HTTP to HTTPS on its own certificate."
  }
  assert {
    condition     = one(aws_cloudfront_distribution.site[0].default_cache_behavior).compress == false
    error_message = "Streamed answers should pass through uncompressed, as they are written."
  }
}

run "with_cloudfront_and_a_domain_the_certificate_is_in_us_east_1" {
  command = plan

  variables {
    cloudfront_enabled = true
    domain_name        = "evidencelab.example.org"
    route53_zone_id    = "Z0123456789"
  }

  assert {
    condition     = length(aws_acm_certificate.cloudfront) == 1 && aws_acm_certificate.cloudfront[0].region == "us-east-1" && length(aws_acm_certificate.site) == 0
    error_message = "CloudFront's certificate must be in us-east-1, and the load balancer needs none."
  }
  assert {
    condition     = local.site_url == "https://evidencelab.example.org" && aws_cloudfront_distribution.site[0].aliases == toset(["evidencelab.example.org"])
    error_message = "CloudFront should serve the domain."
  }
  assert {
    condition     = one(aws_route53_record.site[0].alias).name == "d111111abcdef8.cloudfront.net" && length(aws_route53_record.site_ipv6) == 1
    error_message = "The domain should point at CloudFront, over IPv4 and IPv6."
  }
}

run "with_cloudfront_the_waf_blocks_and_counts_only_the_core_body_and_query_string_size_rules" {
  command = plan

  variables {
    cloudfront_enabled = true
  }

  assert {
    condition     = aws_wafv2_web_acl.site[0].scope == "CLOUDFRONT" && aws_wafv2_web_acl.site[0].region == "us-east-1"
    error_message = "CloudFront web ACLs must be in us-east-1."
  }
  assert {
    condition = toset([for r in aws_wafv2_web_acl.site[0].rule : r.name]) == toset([
      "rate-limit-per-ip",
      "AWSManagedRulesAmazonIpReputationList",
      "AWSManagedRulesKnownBadInputsRuleSet",
      "AWSManagedRulesCommonRuleSet",
    ])
    error_message = "The web ACL should have the rate limit and the three AWS managed rule groups, and no allow list."
  }
  assert {
    condition = alltrue([
      for r in aws_wafv2_web_acl.site[0].rule :
      length(one(r.override_action).none) == 1 if r.name != "rate-limit-per-ip"
    ])
    error_message = "The managed rule groups should block what they match."
  }
  assert {
    condition = [
      for o in one(one(one([for r in aws_wafv2_web_acl.site[0].rule : r if r.name == "AWSManagedRulesCommonRuleSet"]).statement).managed_rule_group_statement).rule_action_override : o.name
    ] == ["SizeRestrictions_BODY", "SizeRestrictions_QUERYSTRING"]
    error_message = "By default only the core rules that block bodies over 8 KB and query strings over 2,048 bytes (Microsoft sign-in's reply) should count instead of block."
  }
  assert {
    condition = alltrue([
      for o in one(one(one([for r in aws_wafv2_web_acl.site[0].rule : r if r.name == "AWSManagedRulesCommonRuleSet"]).statement).managed_rule_group_statement).rule_action_override :
      length(one(o.action_to_use).count) == 1 && length(one(o.action_to_use).block) == 0
    ])
    error_message = "Each overridden core rule should count, not block."
  }
  assert {
    condition     = one(one(one([for r in aws_wafv2_web_acl.site[0].rule : r if r.name == "rate-limit-per-ip"]).statement).rate_based_statement).limit == 2000
    error_message = "The rate limit should be waf_rate_limit requests per address."
  }
  assert {
    condition     = length(aws_wafv2_ip_set.allowed) == 0
    error_message = "No allow list should be made unless waf_allowed_ip_ranges is set."
  }
  assert {
    condition     = output.waf_allow_list_blocks == false
    error_message = "Without an allow list, check-site.sh should fetch the site over the internet."
  }
}

run "waf_allowed_ip_ranges_block_every_other_address" {
  command = plan

  variables {
    cloudfront_enabled    = true
    waf_allowed_ip_ranges = ["203.0.113.0/24", "2001:db8::/32"]
  }

  assert {
    condition     = aws_wafv2_ip_set.allowed["IPV4"].addresses == toset(["203.0.113.0/24"]) && aws_wafv2_ip_set.allowed["IPV6"].addresses == toset(["2001:db8::/32"])
    error_message = "The ranges should be split into an IPv4 and an IPv6 set."
  }
  assert {
    condition = alltrue([
      for r in aws_wafv2_web_acl.site[0].rule :
      r.priority == 0 && length(one(r.action).block) == 1 if r.name == "allowed-ip-ranges"
    ]) && contains([for r in aws_wafv2_web_acl.site[0].rule : r.name], "allowed-ip-ranges")
    error_message = "The allow list should run first and block everything outside the ranges."
  }
  assert {
    condition     = output.waf_allow_list_blocks == true
    error_message = "With a blocking allow list, check-site.sh should check the site through AWS."
  }
}

run "waf_allow_list_in_count_only_mode_does_not_block" {
  command = plan

  variables {
    cloudfront_enabled    = true
    waf_allowed_ip_ranges = ["203.0.113.0/24"]
    waf_count_only        = true
  }

  assert {
    condition     = output.waf_allow_list_blocks == false
    error_message = "A count-only allow list blocks nobody, so check-site.sh can fetch the site."
  }
}

run "waf_count_only_counts_every_rule" {
  command = plan

  variables {
    cloudfront_enabled    = true
    waf_count_only        = true
    waf_allowed_ip_ranges = ["203.0.113.0/24"]
  }

  assert {
    condition = alltrue([
      for r in aws_wafv2_web_acl.site[0].rule :
      (length(r.action) == 1 ? length(one(r.action).count) == 1 && length(one(r.action).block) == 0 : length(one(r.override_action).count) == 1 && length(one(r.override_action).none) == 0)
    ])
    error_message = "In count mode no rule should block."
  }
}

run "waf_rate_limit_zero_turns_the_rate_rule_off" {
  command = plan

  variables {
    cloudfront_enabled = true
    waf_rate_limit     = 0
  }

  assert {
    condition     = !contains([for r in aws_wafv2_web_acl.site[0].rule : r.name], "rate-limit-per-ip")
    error_message = "waf_rate_limit = 0 should remove the rate limit."
  }
}

run "an_unknown_price_class_is_refused" {
  command = plan

  variables {
    cloudfront_price_class = "PriceClass_Cheapest"
  }

  expect_failures = [var.cloudfront_price_class]
}

run "an_allowed_range_that_is_not_cidr_is_refused" {
  command = plan

  variables {
    waf_allowed_ip_ranges = ["203.0.113.7"]
  }

  expect_failures = [var.waf_allowed_ip_ranges]
}

run "an_origin_read_timeout_out_of_range_is_refused" {
  command = plan

  variables {
    cloudfront_origin_read_timeout = 0
  }

  expect_failures = [var.cloudfront_origin_read_timeout]
}

run "a_rate_limit_below_the_waf_minimum_is_refused" {
  command = plan

  variables {
    waf_rate_limit = 5
  }

  expect_failures = [var.waf_rate_limit]
}

# --- Your own pipeline files and branding -------------------------------------

run "without_pipeline_files_nothing_is_shipped" {
  command = plan

  assert {
    condition = (
      length(aws_s3_bucket.pipeline_files) == 0 &&
      length(aws_s3_object.pipeline_files) == 0 &&
      length(aws_iam_role_policy.pipeline_files) == 0
    )
    error_message = "With no pipeline_files_dir there should be no bucket, files or permission."
  }
  assert {
    condition = (
      !local.app_containers["pipeline"].fetch_pipeline_files &&
      !contains(keys(local.app_containers["pipeline"].env), "PIPELINE_FILES_BUCKET")
    )
    error_message = "With no pipeline_files_dir the pipeline task should start as before."
  }
}

run "pipeline_files_are_uploaded_and_copied_into_the_pipeline_task" {
  command = plan

  variables {
    pipeline_files_dir = "tests/fixtures/pipeline-files"
  }

  assert {
    condition     = toset(keys(aws_s3_object.pipeline_files)) == toset(["downloader.py", "sub/list.csv"])
    error_message = "Every file in the folder, sub-folders included, should be uploaded."
  }
  assert {
    condition     = aws_s3_object.pipeline_files["sub/list.csv"].key == "files/sub/list.csv"
    error_message = "Files should keep their place in the folder, under files/."
  }
  assert {
    condition     = aws_s3_bucket.pipeline_files[0].force_destroy
    error_message = "Teardown should delete the files with the bucket."
  }
  assert {
    condition = (
      aws_s3_bucket_public_access_block.pipeline_files[0].block_public_acls &&
      aws_s3_bucket_public_access_block.pipeline_files[0].block_public_policy &&
      aws_s3_bucket_public_access_block.pipeline_files[0].ignore_public_acls &&
      aws_s3_bucket_public_access_block.pipeline_files[0].restrict_public_buckets
    )
    error_message = "The pipeline files bucket must never be public."
  }
  assert {
    condition = (
      local.app_containers["pipeline"].fetch_pipeline_files &&
      local.app_containers["pipeline"].env["PIPELINE_FILES_BUCKET"] == aws_s3_bucket.pipeline_files[0].bucket
    )
    error_message = "The pipeline task should be told the bucket and copy its files before running."
  }
  assert {
    condition = alltrue([
      for c in ["api", "mcp", "migrate"] :
      !local.app_containers[c].fetch_pipeline_files && !contains(keys(local.app_containers[c].env), "PIPELINE_FILES_BUCKET")
    ])
    error_message = "Only the pipeline task should copy the pipeline files."
  }
  assert {
    condition     = strcontains(local.fetch_pipeline_files, "\"/app/custom\"") && strcontains(local.fetch_pipeline_files, "Prefix=\"files/\"")
    error_message = "The pipeline task should copy the bucket's files/ to /app/custom."
  }
  assert {
    condition = (
      toset(data.aws_iam_policy_document.pipeline_files[0].statement[1].actions) == toset(["s3:GetObject"]) &&
      toset(data.aws_iam_policy_document.pipeline_files[0].statement[1].resources) == toset(["arn:aws:s3:::evidencelab-pipeline-files-20261120/files/*"])
    )
    error_message = "The task role should only read the files, and only under files/."
  }
  assert {
    condition = (
      toset(data.aws_iam_policy_document.pipeline_files[0].statement[0].actions) == toset(["s3:ListBucket"]) &&
      toset(one(data.aws_iam_policy_document.pipeline_files[0].statement[0].condition).values) == toset(["files/*"])
    )
    error_message = "The task role should only list the files/ prefix."
  }
}

run "a_pipeline_files_folder_without_files_is_refused" {
  command = plan

  variables {
    pipeline_files_dir = "tests/fixtures/no-such-folder"
  }

  expect_failures = [var.pipeline_files_dir]
}

run "without_a_branding_folder_the_build_falls_back_to_its_own_choice" {
  command = plan

  assert {
    condition     = output.customize_assets_dir == ""
    error_message = "With no customize_assets_dir, the web app build should keep its existing branding choice."
  }
}

run "a_branding_folder_reaches_the_web_app_build" {
  command = plan

  variables {
    customize_assets_dir = "tests/fixtures/branding"
  }

  assert {
    condition     = output.customize_assets_dir == "tests/fixtures/branding"
    error_message = "The web app build reads the branding folder from this output."
  }
}

run "a_branding_folder_without_files_is_refused" {
  command = plan

  variables {
    customize_assets_dir = "tests/fixtures/no-such-folder"
  }

  expect_failures = [var.customize_assets_dir]
}

run "scheduled_backups_cover_postgres_the_documents_and_qdrant" {
  command = plan

  # Known while planning, so the test can check what the backups cover.
  override_resource {
    target          = aws_efs_file_system.data
    override_during = plan
    values = {
      arn = "arn:aws:elasticfilesystem:us-east-2:123456789012:file-system/fs-0123456789abcdef0"
    }
  }
  override_resource {
    target          = aws_instance.qdrant[0]
    override_during = plan
    values = {
      arn = "arn:aws:ec2:us-east-2:123456789012:instance/i-0123456789abcdef0"
    }
  }

  # The database's ARN is unknown while planning; the file share's and
  # Qdrant's are fixed above, so the list's length and their places show
  # what is backed up.
  assert {
    condition     = length(local.backup_resources) == 3
    error_message = "The backups should cover Postgres, the EFS documents and Qdrant's instance."
  }
  assert {
    condition     = local.backup_resources[1] == "arn:aws:elasticfilesystem:us-east-2:123456789012:file-system/fs-0123456789abcdef0"
    error_message = "The backups should cover the EFS file share."
  }
  assert {
    condition     = local.backup_resources[2] == "arn:aws:ec2:us-east-2:123456789012:instance/i-0123456789abcdef0"
    error_message = "The backups should cover Qdrant's instance."
  }
  assert {
    condition     = length(aws_backup_selection.main) == 1
    error_message = "One backup selection should hold the backed-up resources."
  }
  assert {
    condition     = aws_backup_vault.main[0].force_destroy
    error_message = "Removing the deployment should be able to delete its backup vault."
  }
}

run "with_a_qdrant_url_backups_cover_postgres_and_the_documents_only" {
  command = plan

  override_resource {
    target          = aws_efs_file_system.data
    override_during = plan
    values = {
      arn = "arn:aws:elasticfilesystem:us-east-2:123456789012:file-system/fs-0123456789abcdef0"
    }
  }

  variables {
    qdrant_url = "https://cluster.us-east-2-0.aws.cloud.qdrant.io:6333"
  }

  assert {
    condition     = length(local.backup_resources) == 2
    error_message = "With Qdrant Cloud there is no Qdrant instance to back up."
  }
}

run "backup_schedule_and_retention_are_settings" {
  command = plan

  variables {
    backup_schedule       = "cron(30 1 * * ? *)"
    backup_retention_days = 14
  }

  assert {
    condition     = one(aws_backup_plan.main[0].rule).schedule == "cron(30 1 * * ? *)"
    error_message = "backup_schedule should set when backups run."
  }
  assert {
    condition     = one(one(aws_backup_plan.main[0].rule).lifecycle).delete_after == 14
    error_message = "backup_retention_days should set how long backups are kept."
  }
}

run "backups_can_be_turned_off" {
  command = plan

  variables {
    backups_enabled = false
  }

  assert {
    condition     = length(aws_backup_vault.main) == 0 && length(aws_backup_plan.main) == 0 && length(aws_backup_selection.main) == 0 && length(aws_iam_role.backup) == 0
    error_message = "backups_enabled = false should create no backup vault, plan, selection or role."
  }
}

run "a_backup_schedule_that_is_not_cron_is_refused" {
  command = plan

  variables {
    backup_schedule = "weekly"
  }

  expect_failures = [var.backup_schedule]
}

run "the_transfer_bucket_is_private_https_only_and_deletes_uploads" {
  command = plan

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.transfer.block_public_acls,
      aws_s3_bucket_public_access_block.transfer.block_public_policy,
      aws_s3_bucket_public_access_block.transfer.ignore_public_acls,
      aws_s3_bucket_public_access_block.transfer.restrict_public_buckets,
    ])
    error_message = "The transfer bucket must block every kind of public access."
  }
  assert {
    condition     = one(one(aws_s3_bucket_lifecycle_configuration.transfer.rule).expiration).days == 30
    error_message = "Uploads should be deleted after transfer_retention_days."
  }
  assert {
    condition = anytrue([
      for st in data.aws_iam_policy_document.transfer_bucket.statement :
      st.effect == "Deny" && anytrue([for c in st.condition : c.variable == "aws:SecureTransport" && toset(c.values) == toset(["false"])])
    ])
    error_message = "The transfer bucket should refuse requests that don't use HTTPS."
  }
}

run "only_the_restore_task_can_read_the_transfer_bucket" {
  command = plan

  # The mocks give every role the same ARN; give the restore role its own.
  override_resource {
    target          = aws_iam_role.restore
    override_during = plan
    values = {
      arn = "arn:aws:iam::123456789012:role/evidencelab-ecs-restore"
    }
  }

  assert {
    condition     = aws_ecs_task_definition.app["restore"].task_role_arn == "arn:aws:iam::123456789012:role/evidencelab-ecs-restore"
    error_message = "The restore task should run as its own role."
  }
  assert {
    condition = alltrue([
      for name in ["api", "mcp", "migrate", "pipeline"] :
      aws_ecs_task_definition.app[name].task_role_arn != "arn:aws:iam::123456789012:role/evidencelab-ecs-restore"
    ])
    error_message = "No other task should run as the restore role."
  }
  assert {
    condition = [for st in data.aws_iam_policy_document.restore.statement : st.actions] == [
      toset(["s3:ListBucket"]), toset(["s3:GetObject"]), toset(["s3:PutObject", "s3:AbortMultipartUpload"]),
    ]
    error_message = "The restore role should list and read the transfer bucket, and write nothing but dumps."
  }
  assert {
    condition = alltrue([
      for r in data.aws_iam_policy_document.restore.statement[2].resources : endswith(r, "/dumps/*")
    ])
    error_message = "The restore role may write only under dumps/ in the transfer bucket."
  }
  assert {
    condition = alltrue([
      for name in ["api", "mcp", "migrate", "pipeline"] :
      !contains(keys(local.app_containers[name].env), "TRANSFER_BUCKET")
    ]) && contains(keys(local.app_containers["restore"].env), "TRANSFER_BUCKET")
    error_message = "Only the restore task should be told the transfer bucket's name."
  }
}

run "transfer_retention_days_is_a_setting" {
  command = plan

  variables {
    transfer_retention_days = 7
  }

  assert {
    condition     = one(one(aws_s3_bucket_lifecycle_configuration.transfer.rule).expiration).days == 7
    error_message = "transfer_retention_days should set when uploads are deleted."
  }
}

run "a_transfer_retention_below_one_day_is_refused" {
  command = plan

  variables {
    transfer_retention_days = 0
  }

  expect_failures = [var.transfer_retention_days]
}

run "postgres_is_created_on_the_chosen_major_version" {
  command = plan

  assert {
    condition     = data.aws_rds_engine_version.postgres.version == "17"
    error_message = "A new database should use db_engine_version, 17 by default."
  }
}

run "db_engine_version_is_a_setting" {
  command = plan

  variables {
    db_engine_version = "16"
  }

  assert {
    condition     = data.aws_rds_engine_version.postgres.version == "16"
    error_message = "db_engine_version should choose the major version of a new database."
  }
}

run "a_db_engine_version_with_a_minor_version_is_refused" {
  command = plan

  variables {
    db_engine_version = "17.9"
  }

  expect_failures = [var.db_engine_version]
}

# S3 traffic from the private subnets skips the NAT gateway, which charges per
# GB: a gateway endpoint in the deployment's region, on the private route table.
run "s3_traffic_goes_through_a_gateway_endpoint" {
  command = plan

  assert {
    condition     = aws_vpc_endpoint.s3.vpc_endpoint_type == "Gateway"
    error_message = "S3 should have a gateway endpoint, which has no charge (an interface endpoint charges by the hour)."
  }
  assert {
    condition     = aws_vpc_endpoint.s3.service_name == "com.amazonaws.us-east-2.s3"
    error_message = "The S3 endpoint should be for S3 in the deployment's own region."
  }
}

# The runs below share state: the first creates the Qdrant instance (mocked) with
# one Amazon Linux image, the second plans after AWS has published a newer
# one. Qdrant's index lives on its instance's disk, so the instance must keep
# its image rather than be replaced.
run "qdrant_instance_is_created" {
  command = apply

  plan_options {
    target = [aws_instance.qdrant]
  }

  assert {
    condition     = nonsensitive(aws_instance.qdrant[0].ami) == "ami-0123456789abcdef0"
    error_message = "Qdrant's instance should start from the Amazon Linux image of the day it is created."
  }
}

run "a_newer_amazon_linux_image_keeps_the_qdrant_instance" {
  command = plan

  plan_options {
    target = [aws_instance.qdrant]
  }

  override_data {
    target = data.aws_ssm_parameter.al2023_arm64[0]
    values = {
      value = "ami-0fedcba9876543210"
    }
  }

  assert {
    condition     = nonsensitive(aws_instance.qdrant[0].ami) == "ami-0123456789abcdef0"
    error_message = "A newer Amazon Linux image must not replace Qdrant's instance: its disk holds the index."
  }
}

# The same for Postgres: created on PostgreSQL 17's default minor version
# (mocked as 17.9), it keeps that version when AWS's default moves on, because
# AWS applies minor upgrades itself and a deploy must not upgrade or restart it.
run "postgres_is_created" {
  command = apply

  plan_options {
    target = [aws_db_instance.main]
  }

  assert {
    condition     = aws_db_instance.main.engine_version == "17.9"
    error_message = "Postgres should start on PostgreSQL 17's default minor version."
  }
}

run "a_newer_default_postgres_version_keeps_the_database_as_it_is" {
  command = plan

  plan_options {
    target = [aws_db_instance.main]
  }

  override_data {
    target = data.aws_rds_engine_version.postgres
    values = {
      version_actual = "17.10"
    }
  }

  assert {
    condition     = aws_db_instance.main.engine_version == "17.9"
    error_message = "A newer default PostgreSQL version must not make a deploy upgrade the database."
  }
}

# The same endpoint, applied with mocked values, so its route table can be compared.
run "s3_endpoint_is_on_the_private_route_table" {
  command = apply

  plan_options {
    target = [aws_vpc_endpoint.s3]
  }

  assert {
    condition     = length(aws_vpc_endpoint.s3.route_table_ids) == 1 && contains(aws_vpc_endpoint.s3.route_table_ids, aws_route_table.private.id)
    error_message = "The S3 endpoint should be on the private subnets' route table, where the containers run, and only there."
  }
}
