output "site_url" {
  description = "Where the site is served."
  value       = local.site_url
}

output "name" {
  value = var.name
}

output "resource_group" {
  description = "Resource group holding everything this deployment created."
  value       = azurerm_resource_group.main.name
}

output "subscription_id" {
  value = var.subscription_id
}

output "services_enabled" {
  value = var.services_enabled
}

output "registry" {
  description = "Container registry for the web app image."
  value       = azurerm_container_registry.main.name
}

output "registry_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "ui_image_tag" {
  description = "Tag of the web app image the ui app runs."
  value       = var.ui_image_tag
}

output "user_module" {
  value = var.user_module
}

output "anonymous_access" {
  value = var.anonymous_access
}

output "config_json_path" {
  value = var.config_json_path
}

output "api_secret_key" {
  description = "The site's API key. scripts/build-ui-image.sh builds it into the web app when anonymous_access is true."
  value       = random_password.api_secret_key.result
  sensitive   = true
}

output "job_ids" {
  description = "Container Apps jobs, started by scripts/run-job.sh."
  value       = { for k, job in azurerm_container_app_job.this : k => job.id }
}

output "apps" {
  description = "Container apps, once services_enabled is true."
  value = concat(
    [for app in azurerm_container_app.backend : app.name],
    [for app in azurerm_container_app.embedding : app.name],
    [for app in azurerm_container_app.ui : app.name],
  )
}

output "app_image" {
  description = "Image the api, mcp, migrate and pipeline containers run."
  value       = local.app_image
}

output "log_workspace_id" {
  description = "Log Analytics workspace that holds the app and job logs (its workspace ID, for queries)."
  value       = azurerm_log_analytics_workspace.main.workspace_id
}
