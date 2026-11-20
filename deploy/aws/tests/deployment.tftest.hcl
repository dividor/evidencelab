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
  waf_core_rules_to_count        = ["SizeRestrictions_BODY"]
  waf_count_only                 = false

  pipeline_files_dir   = ""
  customize_assets_dir = ""
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

  assert {
    condition     = local.app_environment["AWS_REGION"] == "us-east-2"
    error_message = "The containers should be told the deployment's region."
  }
  assert {
    condition     = aws_ecs_task_definition.app["api"].task_role_arn == aws_iam_role.task.arn
    error_message = "The api should run as the task role that may call Bedrock."
  }
}

# --- CloudFront and AWS WAF --------------------------------------------------

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

run "with_cloudfront_the_waf_blocks_and_counts_only_the_core_body_size_rule" {
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
    ] == ["SizeRestrictions_BODY"]
    error_message = "Only the core rule that blocks bodies over 8 KB should count instead of block."
  }
  assert {
    condition     = one(one(one([for r in aws_wafv2_web_acl.site[0].rule : r if r.name == "rate-limit-per-ip"]).statement).rate_based_statement).limit == 2000
    error_message = "The rate limit should be waf_rate_limit requests per address."
  }
  assert {
    condition     = length(aws_wafv2_ip_set.allowed) == 0
    error_message = "No allow list should be made unless waf_allowed_ip_ranges is set."
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

# The last two runs share state: the first creates the Qdrant instance (mocked) with
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
