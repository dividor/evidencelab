# The Application Load Balancer: the only public entry point. With a domain it
# serves HTTPS with an ACM certificate and redirects HTTP; without one it
# serves plain HTTP on its own address, for testing.

locals {
  https    = var.domain_name != ""
  site_url = local.https ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}

resource "aws_lb" "main" {
  name               = var.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
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
    type             = local.https ? "redirect" : "forward"
    target_group_arn = local.https ? null : aws_lb_target_group.ui.arn

    dynamic "redirect" {
      for_each = local.https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_acm_certificate" "site" {
  count             = local.https ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Keyed by the domain name, which is known before apply; the record's values
# come from the certificate once AWS has issued its validation details.
resource "aws_route53_record" "certificate_validation" {
  for_each = local.https ? toset([var.domain_name]) : toset([])
  zone_id  = var.route53_zone_id
  name     = one([for o in aws_acm_certificate.site[0].domain_validation_options : o.resource_record_name if o.domain_name == each.key])
  type     = one([for o in aws_acm_certificate.site[0].domain_validation_options : o.resource_record_type if o.domain_name == each.key])
  records  = [one([for o in aws_acm_certificate.site[0].domain_validation_options : o.resource_record_value if o.domain_name == each.key])]
  ttl      = 300
}

resource "aws_acm_certificate_validation" "site" {
  count                   = local.https ? 1 : 0
  certificate_arn         = aws_acm_certificate.site[0].arn
  validation_record_fqdns = [for r in aws_route53_record.certificate_validation : r.fqdn]
}

resource "aws_lb_listener" "https" {
  count             = local.https ? 1 : 0
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

resource "aws_route53_record" "site" {
  count   = local.https ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
