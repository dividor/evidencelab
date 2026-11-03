output "site_url" {
  description = "Where the site is served."
  value       = local.site_url
}

output "name" {
  value = var.name
}

output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "services_enabled" {
  value = var.services_enabled
}

output "registry" {
  description = "Artifact Registry repository for the web app image."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}"
}

output "ui_image_tag" {
  description = "Tag of the web app image the web service runs."
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

output "jobs" {
  description = "Cloud Run jobs, started by scripts/run-job.sh."
  value       = { for k, job in google_cloud_run_v2_job.this : k => job.name }
}

output "services" {
  description = "Cloud Run services, once services_enabled is true."
  value = concat(
    [for s in google_cloud_run_v2_service.web : s.name],
    [for s in google_cloud_run_v2_service.embedding : s.name],
  )
}
