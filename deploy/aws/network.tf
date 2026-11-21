# A VPC across two availability zones. The NAT gateway sits in the public
# subnets, and so does the load balancer unless CloudFront is in front of it;
# everything else is in the private subnets and reaches the internet (image
# registries, model providers) through the NAT gateway. S3 is the exception: a
# gateway endpoint carries the private subnets' S3 traffic instead.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  vpc_cidr = "10.0.0.0/16"
  azs      = slice(data.aws_availability_zones.available.names, 0, 2)
  # The VPC's own DNS server is always at the base of its range plus two.
  vpc_dns_server = cidrhost(local.vpc_cidr, 2)
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = var.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = var.name }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(local.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = { Name = "${var.name}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(local.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = { Name = "${var.name}-private-${count.index}" }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${var.name}-nat" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = var.name }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.name}-public" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = { Name = "${var.name}-private" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# The private subnets' S3 traffic goes through this gateway endpoint instead of
# the NAT gateway. A gateway endpoint has no charge; the NAT gateway charges for
# every GB it carries, and on one deployment it was most of the bill on the days
# data was restored and dumped. This covers the transfer bucket, the pipeline
# files and the web app image's layers, which ECR keeps in S3. Docker Hub and
# Bedrock still go through the NAT gateway, and so does S3 in other regions.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = { Name = "${var.name}-s3" }
}

# --- Security groups --------------------------------------------------------

# The load balancer: the only thing reachable from the internet, or with
# CloudFront, reachable only from CloudFront's origin-facing servers.
resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "Evidence Lab load balancer"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = local.cloudfront ? null : "0.0.0.0/0"
  prefix_list_id    = local.cloudfront ? data.aws_ec2_managed_prefix_list.cloudfront[0].id : null
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = local.cloudfront ? "HTTP from CloudFront" : "HTTP (redirected to HTTPS when a domain is set)"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  count             = local.alb_https ? 1 : 0
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_ui" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.tasks.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
  description                  = "To the ui containers"
}

# The containers: reachable from the load balancer (ui) and from each other.
resource "aws_security_group" "tasks" {
  name        = "${var.name}-tasks"
  description = "Evidence Lab containers"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
  description                  = "Load balancer to ui"
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_tasks" {
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = aws_security_group.tasks.id
  ip_protocol                  = "tcp"
  from_port                    = 0
  to_port                      = 65535
  description                  = "Between the services"
}

resource "aws_vpc_security_group_egress_rule" "tasks_out" {
  security_group_id = aws_security_group.tasks.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Data services, image registries and model providers"
}

# The data services: reachable only from the containers.
resource "aws_security_group" "data" {
  name        = "${var.name}-data"
  description = "Evidence Lab databases and file share"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "data_from_tasks" {
  for_each = {
    postgres = 5432
    redis    = 6379
    efs      = 2049
    qdrant   = 6333
  }
  security_group_id            = aws_security_group.data.id
  referenced_security_group_id = aws_security_group.tasks.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
  description                  = each.key
}

resource "aws_vpc_security_group_egress_rule" "data_out" {
  security_group_id = aws_security_group.data.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Qdrant on EC2 pulls its image through the NAT gateway"
}
