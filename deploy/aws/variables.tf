variable "name" {
  description = "Deployment name. Prefixes every resource and tags it, so several deployments can share an account."
  type        = string
  default     = "evidencelab"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.name))
    error_message = "name must be 2-21 lower-case letters, digits or hyphens, starting with a letter."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-2"
}

variable "evidencelab_image" {
  description = "Image for the api, mcp, pipeline and migrate containers, without the tag."
  type        = string
  default     = "docker.io/astrobagel/evidencelab"
}

variable "evidencelab_version" {
  description = "Tag of evidencelab_image to run, for example 1.6.5 or rc-v1.6.5."
  type        = string
}

variable "ui_image_tag" {
  description = "Tag of the web app image pushed to this deployment's ECR repository by scripts/build-ui-image.sh."
  type        = string
  default     = "latest"
}

variable "embedding_image" {
  description = "Embedding server image."
  type        = string
  default     = "docker.io/michaelf34/infinity:0.0.70"
}

variable "embedding_model" {
  description = "Model the embedding server loads (INFINITY_MODEL_ID)."
  type        = string
  default     = "intfloat/multilingual-e5-large"
}

variable "config_json_path" {
  description = "Path to the config.json the deployment runs with. The same file must be used to build the web app image."
  type        = string
}

variable "services_enabled" {
  description = "Run the ui, api, mcp and embedding services. Leave false on the first apply, push the web app image and run the migrate task, then set true."
  type        = bool
  default     = false
}

variable "domain_name" {
  description = "Domain for the site, for example evidencelab.example.org. Empty serves plain HTTP on the load balancer's own address, for testing only."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone for domain_name. Used to validate the HTTPS certificate and to point the domain at the load balancer."
  type        = string
  default     = ""
}

variable "qdrant_url" {
  description = "URL of an existing Qdrant, such as a Qdrant Cloud cluster. Empty runs Qdrant on a small EC2 instance in the private subnets."
  type        = string
  default     = ""
}

variable "qdrant_api_key" {
  description = "API key for qdrant_url. Ignored when Qdrant runs on EC2, which gets a generated key."
  type        = string
  default     = ""
  sensitive   = true
}

variable "qdrant_instance_type" {
  description = "EC2 instance type for Qdrant when qdrant_url is empty (arm64)."
  type        = string
  default     = "t4g.medium"
}

variable "qdrant_volume_gb" {
  description = "Disk size for Qdrant on EC2, in GB."
  type        = number
  default     = 30
}

variable "provider_secret_names" {
  description = "Names of the model provider settings the containers need, for example [\"AZURE_FOUNDRY_KEY\", \"AZURE_FOUNDRY_ENDPOINT\"]. Their values go in the <name>/providers secret, which scripts/deploy.sh fills from your environment, so they never pass through Terraform."
  type        = list(string)
  default     = []
}

variable "user_module" {
  description = "Sign-in mode (USER_MODULE): on_passive lets visitors use the site signed out; on_active requires sign-in."
  type        = string
  default     = "on_passive"

  validation {
    condition     = contains(["on_passive", "on_active"], var.user_module)
    error_message = "user_module must be on_passive or on_active: the site is public, so sign-in must be on. For visitors who are not signed in, use anonymous_access."
  }
}

variable "anonymous_access" {
  description = "Let visitors use the site without signing in, as evidencelab.ai does. The web app is then built with the API key, which anyone can read from the page, so use it for demonstrations and public read-only sites only."
  type        = bool
  default     = false
}

variable "extra_environment" {
  description = "Further non-secret settings for the api, mcp, pipeline and migrate containers, such as RATE_LIMIT_DEFAULT."
  type        = map(string)
  default     = {}
}

variable "api" {
  description = "api service size and copies."
  type        = object({ cpu = number, memory = number, count = number })
  default     = { cpu = 2048, memory = 8192, count = 2 }
}

variable "mcp" {
  description = "mcp service size and copies."
  type        = object({ cpu = number, memory = number, count = number })
  default     = { cpu = 512, memory = 2048, count = 2 }
}

variable "ui" {
  description = "ui service size and copies."
  type        = object({ cpu = number, memory = number, count = number })
  default     = { cpu = 256, memory = 512, count = 2 }
}

variable "embedding" {
  description = "Embedding service size. One copy always runs."
  type        = object({ cpu = number, memory = number })
  default     = { cpu = 1024, memory = 4096 }
}

variable "migrate_task" {
  description = "migrate task size."
  type        = object({ cpu = number, memory = number })
  default     = { cpu = 512, memory = 1024 }
}

variable "pipeline_task" {
  description = "pipeline task size."
  type        = object({ cpu = number, memory = number })
  default     = { cpu = 4096, memory = 16384 }
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  description = "RDS storage, in GB."
  type        = number
  default     = 50
}

variable "db_multi_az" {
  description = "Keep a standby database in a second availability zone."
  type        = bool
  default     = true
}

variable "db_backup_retention_days" {
  description = "Days of automated database backups."
  type        = number
  default     = 7
}

variable "db_skip_final_snapshot" {
  description = "Skip the final database snapshot on destroy. Keep false for real data; set true for throwaway test deployments."
  type        = bool
  default     = false
}

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "log_retention_days" {
  description = "Days to keep container logs."
  type        = number
  default     = 30
}
