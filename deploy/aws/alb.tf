# The Application Load Balancer. On its own it is the public entry point: with
# a domain it serves HTTPS with an ACM certificate and redirects HTTP; without
# one it serves plain HTTP on its own address, for testing.
#
# With cloudfront_enabled it moves to the private subnets and serves plain
# HTTP to CloudFront only, which serves the site over HTTPS (cloudfront.tf).

locals {
  cloudfront = var.cloudfront_enabled
  domain     = var.domain_name != ""
  # The load balancer serves HTTPS itself only without CloudFront.
  alb_https = local.domain && !local.cloudfront
  # Visitors reach the site over HTTPS with a domain or through CloudFront.
  site_https = local.domain || local.cloudfront
  site_url = (
    local.domain ? "https://${var.domain_name}" :
    local.cloudfront ? "https://${aws_cloudfront_distribution.site[0].domain_name}" :
    "http://${aws_lb.main.dns_name}"
  )
  # The domain's certificate: in us-east-1 for CloudFront, otherwise in the
  # deployment's region for the load balancer.
  certificate = (
    !local.domain ? null :
    local.cloudfront ? aws_acm_certificate.cloudfront[0] : aws_acm_certificate.site[0]
  )
}

resource "aws_lb" "main" {
  name               = var.name
  load_balancer_type = "application"
  internal           = local.cloudfront
  subnets            = local.cloudfront ? aws_subnet.private[*].id : aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
  # Chat answers and MCP connections stream for minutes.
  idle_timeout = 300
}

resource "aws_lb_target_group" "ui" {
  name        = "${var.name}-ui"
  port        = 80
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = local.alb_https ? "redirect" : "forward"
    target_group_arn = local.alb_https ? null : aws_lb_target_group.ui.arn

    dynamic "redirect" {
      for_each = local.alb_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_acm_certificate" "site" {
  count             = local.alb_https ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Keyed by the domain name, which is known before apply; the record's values
# come from the certificate once AWS has issued its validation details.
resource "aws_route53_record" "certificate_validation" {
  for_each = local.domain ? toset([var.domain_name]) : toset([])
  zone_id  = var.route53_zone_id
  name     = one([for o in local.certificate.domain_validation_options : o.resource_record_name if o.domain_name == each.key])
  type     = one([for o in local.certificate.domain_validation_options : o.resource_record_type if o.domain_name == each.key])
  records  = [one([for o in local.certificate.domain_validation_options : o.resource_record_value if o.domain_name == each.key])]
  ttl      = 300
}

resource "aws_acm_certificate_validation" "site" {
  count                   = local.alb_https ? 1 : 0
  certificate_arn         = aws_acm_certificate.site[0].arn
  validation_record_fqdns = [for r in aws_route53_record.certificate_validation : r.fqdn]
}

resource "aws_lb_listener" "https" {
  count             = local.alb_https ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.site[0].certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ui.arn
  }
}

# The domain points at CloudFront when it is on, otherwise at the load balancer.
resource "aws_route53_record" "site" {
  count   = local.domain ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = local.cloudfront ? aws_cloudfront_distribution.site[0].domain_name : aws_lb.main.dns_name
    zone_id                = local.cloudfront ? aws_cloudfront_distribution.site[0].hosted_zone_id : aws_lb.main.zone_id
    evaluate_target_health = !local.cloudfront
  }
}

# CloudFront also answers over IPv6.
resource "aws_route53_record" "site_ipv6" {
  count   = local.domain && local.cloudfront ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.site[0].domain_name
    zone_id                = aws_cloudfront_distribution.site[0].hosted_zone_id
    evaluate_target_health = false
  }
}
