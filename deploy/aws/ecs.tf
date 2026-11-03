# The ECS cluster, the services the containers find each other by, and the
# ui, api, mcp and embedding services plus the migrate and pipeline tasks.

resource "aws_ecs_cluster" "main" {
  name = var.name
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${var.name}.internal"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "this" {
  for_each = toset(["api", "mcp", "embedding"])
  name     = each.key

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

resource "aws_cloudwatch_log_group" "this" {
  for_each          = toset(["ui", "api", "mcp", "embedding", "migrate", "pipeline"])
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = var.log_retention_days
}

locals {
  namespace     = aws_service_discovery_private_dns_namespace.main.name
  api_url       = "http://api.${local.namespace}:8000"
  mcp_url       = "http://mcp.${local.namespace}:8001"
  embedding_url = "http://embedding.${local.namespace}:7997"
  app_image     = "${var.evidencelab_image}:${var.evidencelab_version}"

  # config.json is too big for a container setting (92 KB), so it travels
  # compressed and is written to /app/config.json when the container starts,
  # together with the RDS certificate bundle.
  prepare_and_run = join(" ", [
    "python -c 'import base64, gzip, os;",
    "open(\"/app/config.json\", \"wb\").write(gzip.decompress(base64.b64decode(os.environ[\"EVIDENCELAB_CONFIG_GZ\"])));",
    "open(\"/tmp/rds-ca.pem\", \"w\").write(os.environ[\"RDS_CA_BUNDLE\"])'",
    "&& exec \"$@\"",
  ])

  app_environment = merge(var.extra_environment, {
    EVIDENCELAB_CONFIG_GZ = base64gzip(file(var.config_json_path))
    RDS_CA_BUNDLE         = data.http.rds_ca_bundle.response_body
    QDRANT_HOST           = local.qdrant_url
    POSTGRES_HOST         = aws_db_instance.main.address
    POSTGRES_PORT         = tostring(aws_db_instance.main.port)
    POSTGRES_DB           = aws_db_instance.main.db_name
    POSTGRES_USER         = aws_db_instance.main.username
    PGSSLMODE             = "verify-full"
    PGSSLROOTCERT         = "/tmp/rds-ca.pem"
    RATELIMIT_STORAGE_URL = "rediss://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
    EMBEDDING_API_URL     = local.embedding_url
    DATA_MOUNT_PATH       = "/app/data"
    PYTHONPATH            = "/app"
    USER_MODULE           = var.user_module
    APP_BASE_URL          = local.site_url
    CORS_ALLOWED_ORIGINS  = local.site_url
    AUTH_COOKIE_SECURE    = local.https ? "true" : "false"
  })

  app_secrets_refs = concat(
    [for k in ["API_SECRET_KEY", "AUTH_SECRET_KEY", "KEY_ENCRYPTION_KEY", "QDRANT_API_KEY"] : { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }],
    [for k in var.provider_secret_names : { name = k, valueFrom = "${aws_secretsmanager_secret.providers.arn}:${k}::" }],
    [{ name = "POSTGRES_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" }],
  )

  # One definition per Evidence Lab image container; the services and tasks
  # differ only in command, port, size and extra settings.
  app_containers = {
    api = {
      command = ["uvicorn", "ui.backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
      port    = 8000
      size    = var.api
      env = {
        API_ROOT_PATH       = "/api"
        FORWARDED_ALLOW_IPS = local.vpc_cidr
      }
    }
    mcp = {
      command = ["python", "-m", "mcp_server.http_server"]
      port    = 8001
      size    = var.mcp
      env     = {}
    }
    migrate = {
      command = ["alembic", "upgrade", "head"]
      port    = null
      size    = var.migrate_task
      env     = {}
    }
    # Always started with its own command by scripts/run-task.sh.
    pipeline = {
      command = ["python", "-m", "pipeline.orchestrator", "--help"]
      port    = null
      size    = var.pipeline_task
      env     = {}
    }
  }
}

resource "aws_ecs_task_definition" "app" {
  for_each                 = local.app_containers
  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.size.cpu
  memory                   = each.value.size.memory
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  # The image is about 15 GB, close to Fargate's default 20 GB of task storage.
  ephemeral_storage {
    size_in_gib = 40
  }

  volume {
    name = "data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.data.id
      transit_encryption = "ENABLED"
    }
  }

  container_definitions = jsonencode([{
    name        = each.key
    image       = local.app_image
    essential   = true
    entryPoint  = ["sh", "-c", local.prepare_and_run, "evidencelab"]
    command     = each.value.command
    environment = [for k, v in merge(local.app_environment, each.value.env) : { name = k, value = v }]
    secrets     = local.app_secrets_refs
    portMappings = each.value.port == null ? [] : [{
      containerPort = each.value.port
      protocol      = "tcp"
    }]
    mountPoints = [{ sourceVolume = "data", containerPath = "/app/data", readOnly = false }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this[each.key].name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }])
}

resource "aws_ecs_task_definition" "embedding" {
  family                   = "${var.name}-embedding"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.embedding.cpu
  memory                   = var.embedding.memory
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "embedding"
    image     = var.embedding_image
    essential = true
    command   = ["v2"]
    environment = [
      { name = "INFINITY_MODEL_ID", value = var.embedding_model },
      { name = "INFINITY_BATCH_SIZE", value = "8" },
      { name = "INFINITY_PORT", value = "7997" },
      { name = "PYTHONUNBUFFERED", value = "1" },
    ]
    portMappings = [{ containerPort = 7997, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this["embedding"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "embedding"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "ui" {
  family                   = "${var.name}-ui"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ui.cpu
  memory                   = var.ui.memory
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "ui"
    image     = "${aws_ecr_repository.ui.repository_url}:${var.ui_image_tag}"
    essential = true
    environment = [
      { name = "API_UPSTREAM", value = local.api_url },
      { name = "MCP_UPSTREAM", value = local.mcp_url },
      { name = "NGINX_RESOLVER", value = local.vpc_dns_server },
      { name = "NGINX_REAL_IP_FROM", value = local.vpc_cidr },
    ]
    portMappings = [{ containerPort = 80, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this["ui"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "ui"
      }
    }
  }])
}

locals {
  network_configuration = {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.tasks.id]
  }
}

resource "aws_ecs_service" "backend" {
  for_each = {
    api       = { task = aws_ecs_task_definition.app["api"].arn, count = var.api.count }
    mcp       = { task = aws_ecs_task_definition.app["mcp"].arn, count = var.mcp.count }
    embedding = { task = aws_ecs_task_definition.embedding.arn, count = 1 }
  }
  name            = each.key
  cluster         = aws_ecs_cluster.main.id
  task_definition = each.value.task
  desired_count   = var.services_enabled ? each.value.count : 0
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = local.network_configuration.subnets
    security_groups = local.network_configuration.security_groups
  }

  service_registries {
    registry_arn = aws_service_discovery_service.this[each.key].arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_efs_mount_target.data]
}

resource "aws_ecs_service" "ui" {
  name            = "ui"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui.arn
  desired_count   = var.services_enabled ? var.ui.count : 0
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = local.network_configuration.subnets
    security_groups = local.network_configuration.security_groups
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ui.arn
    container_name   = "ui"
    container_port   = 80
  }

  health_check_grace_period_seconds = 60

  # No circuit breaker here: nginx looks up the api's address when it starts,
  # so ui tasks fail until the first api task is running (its image takes
  # minutes to pull). ECS keeps replacing them until one starts.
  depends_on = [aws_ecs_service.backend, aws_lb_listener.http]
}
