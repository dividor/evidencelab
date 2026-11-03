output "site_url" {
  description = "Where the site is served."
  value       = local.site_url
}

output "name" {
  value = var.name
}

output "region" {
  value = var.region
}

output "services_enabled" {
  value = var.services_enabled
}

output "providers_secret_id" {
  description = "Secret the model provider keys go in (scripts/deploy.sh fills it)."
  value       = aws_secretsmanager_secret.providers.id
}

output "provider_secret_names" {
  value = var.provider_secret_names
}

output "cluster" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.main.name
}

output "ui_repository_url" {
  description = "ECR repository the web app image is pushed to."
  value       = aws_ecr_repository.ui.repository_url
}

output "ui_image_tag" {
  value = var.ui_image_tag
}

output "anonymous_access" {
  description = "Whether the web app image is built with the API key (scripts/build-ui-image.sh reads this)."
  value       = var.anonymous_access
}

output "app_secret_id" {
  description = "Secret holding the generated app keys, including API_SECRET_KEY."
  value       = aws_secretsmanager_secret.app.id
}

output "user_module" {
  description = "Sign-in mode; the web app image must be built with the same value."
  value       = var.user_module
}

output "private_subnet_ids" {
  description = "Subnets the migrate and pipeline tasks run in."
  value       = aws_subnet.private[*].id
}

output "tasks_security_group_id" {
  value = aws_security_group.tasks.id
}

output "migrate_task_definition" {
  value = aws_ecs_task_definition.app["migrate"].family
}

output "pipeline_task_definition" {
  value = aws_ecs_task_definition.app["pipeline"].family
}

output "log_groups" {
  description = "CloudWatch log group of each service and task."
  value       = { for k, g in aws_cloudwatch_log_group.this : k => g.name }
}

output "config_json_path" {
  description = "config.json the deployment runs with; the web app image is built from the same file."
  value       = var.config_json_path
}
