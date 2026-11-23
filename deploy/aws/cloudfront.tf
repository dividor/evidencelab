# With cloudfront_enabled: CloudFront in front of the site, with an AWS WAF
# web ACL. The load balancer sits in the private subnets and CloudFront reaches
# it through a VPC origin, so nothing else on the internet can. CloudFront
# serves HTTPS on its own cloudfront.net address, or on domain_name with a
# certificate in us-east-1, where CloudFront certificates and web ACLs live.

# --- Origin -----------------------------------------------------------------

# CloudFront's origin-facing servers; the load balancer accepts only these.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  count = local.cloudfront ? 1 : 0
  name  = "com.amazonaws.global.cloudfront.origin-facing"
}

# Plain HTTP between CloudFront and the load balancer: the load balancer has
# no address on the internet, and no certificate can match its internal name.
resource "aws_cloudfront_vpc_origin" "alb" {
  count = local.cloudfront ? 1 : 0

  vpc_origin_endpoint_config {
    name                   = var.name
    arn                    = aws_lb.main.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

# --- Distribution -----------------------------------------------------------

# Pages, the API, MCP and A2A are never cached, and reach nginx with every
# header, cookie and query string, including the Host the visitor used.
data "aws_cloudfront_cache_policy" "disabled" {
  count = local.cloudfront ? 1 : 0
  name  = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  count = local.cloudfront ? 1 : 0
  name  = "Managed-AllViewer"
}

# The web app's built files have content hashes in their names and nginx
# marks them immutable, so CloudFront can keep them.
data "aws_cloudfront_cache_policy" "optimized" {
  count = local.cloudfront ? 1 : 0
  name  = "Managed-CachingOptimized"
}

resource "aws_acm_certificate" "cloudfront" {
  count             = local.cloudfront && local.domain ? 1 : 0
  region            = "us-east-1"
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "cloudfront" {
  count                   = local.cloudfront && local.domain ? 1 : 0
  region                  = "us-east-1"
  certificate_arn         = aws_acm_certificate.cloudfront[0].arn
  validation_record_fqdns = [for r in aws_route53_record.certificate_validation : r.fqdn]
}

locals {
  all_methods = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
}

resource "aws_cloudfront_distribution" "site" {
  count           = local.cloudfront ? 1 : 0
  enabled         = true
  comment         = var.name
  price_class     = var.cloudfront_price_class
  http_version    = "http2and3"
  is_ipv6_enabled = true
  aliases         = local.domain ? [var.domain_name] : []
  web_acl_id      = aws_wafv2_web_acl.site[0].arn

  origin {
    origin_id   = "load-balancer"
    domain_name = aws_lb.main.dns_name

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.alb[0].id
      # Also the longest silence allowed inside a streamed answer.
      origin_read_timeout = var.cloudfront_origin_read_timeout
    }
  }

  default_cache_behavior {
    target_origin_id         = "load-balancer"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = local.all_methods
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled[0].id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer[0].id
    # Streamed answers pass through as they are written.
    compress = false
  }

  ordered_cache_behavior {
    path_pattern           = "/static/*"
    target_origin_id       = "load-balancer"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized[0].id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.domain
    acm_certificate_arn            = local.domain ? aws_acm_certificate_validation.cloudfront[0].certificate_arn : null
    ssl_support_method             = local.domain ? "sni-only" : null
    minimum_protocol_version       = local.domain ? "TLSv1.2_2021" : null
  }
}

# --- AWS WAF ----------------------------------------------------------------

locals {
  waf_allow_list = length(var.waf_allowed_ip_ranges) > 0
  waf_allowed_ranges = {
    IPV4 = [for c in var.waf_allowed_ip_ranges : c if !strcontains(c, ":")]
    IPV6 = [for c in var.waf_allowed_ip_ranges : c if strcontains(c, ":")]
  }
  # AWS managed rule groups, in the order they run.
  waf_managed_groups = [
    "AWSManagedRulesAmazonIpReputationList",
    "AWSManagedRulesKnownBadInputsRuleSet",
    "AWSManagedRulesCommonRuleSet",
  ]
}

resource "aws_wafv2_ip_set" "allowed" {
  for_each           = local.cloudfront && local.waf_allow_list ? local.waf_allowed_ranges : {}
  region             = "us-east-1"
  name               = "${var.name}-allowed-${lower(each.key)}"
  scope              = "CLOUDFRONT"
  ip_address_version = each.key
  addresses          = each.value

  # Switching the allow list off removes these IP sets and the web ACL's rule
  # that uses them. AWS refuses to delete an IP set a rule still references
  # (WAFAssociatedItemException), and by default Terraform deletes the IP sets
  # first. With create_before_destroy, it updates the web ACL first, then
  # deletes them.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_wafv2_web_acl" "site" {
  count  = local.cloudfront ? 1 : 0
  region = "us-east-1"
  name   = var.name
  scope  = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # Only the listed addresses get through.
  dynamic "rule" {
    for_each = local.waf_allow_list ? [1] : []
    content {
      name     = "allowed-ip-ranges"
      priority = 0

      action {
        dynamic "block" {
          for_each = var.waf_count_only ? [] : [1]
          content {}
        }
        dynamic "count" {
          for_each = var.waf_count_only ? [1] : []
          content {}
        }
      }

      statement {
        not_statement {
          statement {
            or_statement {
              statement {
                ip_set_reference_statement {
                  arn = aws_wafv2_ip_set.allowed["IPV4"].arn
                }
              }
              statement {
                ip_set_reference_statement {
                  arn = aws_wafv2_ip_set.allowed["IPV6"].arn
                }
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-allowed-ip-ranges"
        sampled_requests_enabled   = true
      }
    }
  }

  # An address that sends more than waf_rate_limit requests in 5 minutes is
  # blocked until its rate drops again.
  dynamic "rule" {
    for_each = var.waf_rate_limit > 0 ? [1] : []
    content {
      name     = "rate-limit-per-ip"
      priority = 1

      action {
        dynamic "block" {
          for_each = var.waf_count_only ? [] : [1]
          content {}
        }
        dynamic "count" {
          for_each = var.waf_count_only ? [1] : []
          content {}
        }
      }

      statement {
        rate_based_statement {
          limit                 = var.waf_rate_limit
          aggregate_key_type    = "IP"
          evaluation_window_sec = 300
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-rate-limit-per-ip"
        sampled_requests_enabled   = true
      }
    }
  }

  dynamic "rule" {
    for_each = local.waf_managed_groups
    content {
      name     = rule.value
      priority = 2 + rule.key

      override_action {
        dynamic "none" {
          for_each = var.waf_count_only ? [] : [1]
          content {}
        }
        dynamic "count" {
          for_each = var.waf_count_only ? [1] : []
          content {}
        }
      }

      statement {
        managed_rule_group_statement {
          name        = rule.value
          vendor_name = "AWS"

          # Core rules that would block normal Evidence Lab requests only count.
          dynamic "rule_action_override" {
            for_each = rule.value == "AWSManagedRulesCommonRuleSet" ? var.waf_core_rules_to_count : []
            content {
              name = rule_action_override.value
              action_to_use {
                count {}
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-${rule.value}"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.name
    sampled_requests_enabled   = true
  }
}
