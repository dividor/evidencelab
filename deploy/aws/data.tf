# Postgres, Redis, the shared file share, Qdrant and the keys the containers use.

# --- Postgres ---------------------------------------------------------------

data "aws_rds_engine_version" "postgres" {
  engine       = "postgres"
  version      = "16"
  default_only = true
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = data.aws_rds_engine_version.postgres.version_actual
  instance_class = var.db_instance_class

  db_name  = "evidencelab"
  username = "evidencelab"
  # RDS creates the password and keeps it in Secrets Manager, so it never
  # passes through Terraform.
  manage_master_user_password = true

  allocated_storage      = var.db_allocated_storage_gb
  storage_type           = "gp3"
  storage_encrypted      = true
  multi_az               = var.db_multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.data.id]
  publicly_accessible    = false

  backup_retention_period    = var.db_backup_retention_days
  skip_final_snapshot        = var.db_skip_final_snapshot
  final_snapshot_identifier  = var.db_skip_final_snapshot ? null : "${var.name}-final"
  auto_minor_version_upgrade = true
  apply_immediately          = true
}

# The certificate authorities RDS signs its server certificates with, so the
# containers can check the database's certificate (PGSSLMODE=verify-full).
data "http" "rds_ca_bundle" {
  url = "https://truststore.pki.rds.amazonaws.com/${var.region}/${var.region}-bundle.pem"
}

# --- Redis (shared rate-limit counts) ---------------------------------------

resource "aws_elasticache_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = var.name
  description                = "Evidence Lab rate-limit counts"
  engine                     = "valkey"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 1
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.data.id]
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  apply_immediately          = true
}

# --- Shared file share (/app/data) ------------------------------------------

resource "aws_efs_file_system" "data" {
  creation_token   = "${var.name}-data"
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"

  tags = { Name = "${var.name}-data" }
}

resource "aws_efs_mount_target" "data" {
  count           = 2
  file_system_id  = aws_efs_file_system.data.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.data.id]
}

# --- Qdrant -----------------------------------------------------------------

locals {
  qdrant_on_ec2 = var.qdrant_url == ""
  qdrant_url    = local.qdrant_on_ec2 ? "http://${aws_instance.qdrant[0].private_ip}:6333" : var.qdrant_url
  qdrant_key    = local.qdrant_on_ec2 ? random_password.qdrant_api_key.result : var.qdrant_api_key
  qdrant_image  = "qdrant/qdrant:v1.18.3"
}

resource "random_password" "qdrant_api_key" {
  length  = 40
  special = false
}

data "aws_ssm_parameter" "al2023_arm64" {
  count = local.qdrant_on_ec2 ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "qdrant" {
  count                  = local.qdrant_on_ec2 ? 1 : 0
  ami                    = data.aws_ssm_parameter.al2023_arm64[0].value
  instance_type          = var.qdrant_instance_type
  subnet_id              = aws_subnet.private[0].id
  vpc_security_group_ids = [aws_security_group.data.id]

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.qdrant_volume_gb
    encrypted   = true
  }

  # Docker runs Qdrant with its storage on the instance's disk, restarting it
  # with the instance. Changing the key or image replaces the instance.
  user_data_replace_on_change = true
  user_data                   = <<-EOT
    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    systemctl enable --now docker
    mkdir -p /var/lib/qdrant/storage
    docker run -d --name qdrant --restart always -p 6333:6333 \
      -v /var/lib/qdrant/storage:/qdrant/storage \
      -e QDRANT__SERVICE__API_KEY='${random_password.qdrant_api_key.result}' \
      ${local.qdrant_image}
  EOT

  tags = { Name = "${var.name}-qdrant" }

  depends_on = [aws_nat_gateway.main, aws_route_table_association.private]
}

# --- Keys -------------------------------------------------------------------

resource "random_password" "api_secret_key" {
  length  = 64
  special = false
}

resource "random_password" "auth_secret_key" {
  length  = 64
  special = false
}

# KEY_ENCRYPTION_KEY must be a Fernet key: 32 random bytes in URL-safe base64.
resource "random_bytes" "key_encryption_key" {
  length = 32
}

locals {
  app_secrets = {
    API_SECRET_KEY     = random_password.api_secret_key.result
    AUTH_SECRET_KEY    = random_password.auth_secret_key.result
    KEY_ENCRYPTION_KEY = replace(replace(random_bytes.key_encryption_key.base64, "+", "-"), "/", "_")
    QDRANT_API_KEY     = local.qdrant_key
  }
}

resource "aws_secretsmanager_secret" "app" {
  name = "${var.name}/app"
  # Delete straight away on destroy, so a new deployment can reuse the name.
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode(local.app_secrets)
}

# Model provider keys. Terraform creates the secret but never its value:
# scripts/deploy.sh puts the values in from your environment, so they stay out
# of the Terraform state. Containers fail to start if a named key is missing.
resource "aws_secretsmanager_secret" "providers" {
  name                    = "${var.name}/providers"
  recovery_window_in_days = 0
}

# --- Web app image registry -------------------------------------------------

resource "aws_ecr_repository" "ui" {
  name                 = "${var.name}/ui"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}
