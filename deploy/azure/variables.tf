variable "subscription_id" {
  description = "Azure subscription to deploy into. Check it with: az account show --query id -o tsv"
  type        = string
}

variable "name" {
  description = "Deployment name. Names the resource group that holds everything, and prefixes and tags every resource."
  type        = string
  default     = "evidencelab"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,17}$", var.name))
    error_message = "name must be 2-18 lower-case letters, digits or hyphens, starting with a letter."
  }
}

variable "location" {
  description = "Azure region. It must offer Container Apps, PostgreSQL flexible server, Managed Redis and the models in model_deployments."
  type        = string
  default     = "eastus2"
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
  description = "Tag of the web app image in this deployment's registry. scripts/build-ui-image.sh pushes a new tag on every build, and scripts/deploy.sh passes it here."
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
  description = "Create the ui, api, mcp and embedding apps. Leave false on the first apply, push the web app image and run the migrate job, then set true."
  type        = bool
  default     = false
}

variable "model_deployments" {
  description = "Models deployed in the deployment's Azure AI Foundry resource. Each key is the deployment name, which config.json refers to as the model. capacity is in thousands of tokens per minute for OpenAI models."
  type = map(object({
    format   = string
    model    = string
    version  = string
    sku      = string
    capacity = number
  }))
  default = {
    "text-embedding-3-small"  = { format = "OpenAI", model = "text-embedding-3-small", version = "1", sku = "GlobalStandard", capacity = 150 }
    "gpt-4.1-mini"            = { format = "OpenAI", model = "gpt-4.1-mini", version = "2025-04-14", sku = "GlobalStandard", capacity = 100 }
    "Cohere-rerank-v4.0-fast" = { format = "Cohere", model = "Cohere-rerank-v4.0-fast", version = "1", sku = "GlobalStandard", capacity = 20 }
  }
}

variable "qdrant_url" {
  description = "URL of an existing Qdrant, such as a Qdrant Cloud cluster. Empty runs Qdrant on a small virtual machine in the deployment's network."
  type        = string
  default     = ""
}

variable "qdrant_api_key" {
  description = "API key for qdrant_url. Ignored when Qdrant runs on the virtual machine, which gets a generated key."
  type        = string
  default     = ""
  sensitive   = true
}

variable "qdrant_vm_size" {
  description = "Virtual machine size for Qdrant when qdrant_url is empty."
  type        = string
  default     = "Standard_B2s"
}

variable "qdrant_disk_gb" {
  description = "Disk size for Qdrant on the virtual machine, in GB."
  type        = number
  default     = 30
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

# Container sizes. On the Consumption profile, memory must be twice the vCPU
# count in GB (for example 2 vCPU with 4Gi), up to 4 vCPU and 8Gi.

variable "api" {
  description = "api app size and replicas."
  type        = object({ cpu = number, memory = string, replicas = number })
  default     = { cpu = 4, memory = "8Gi", replicas = 2 }
}

variable "mcp" {
  description = "mcp app size and replicas."
  type        = object({ cpu = number, memory = string, replicas = number })
  default     = { cpu = 1, memory = "2Gi", replicas = 2 }
}

variable "ui" {
  description = "ui app size and replicas."
  type        = object({ cpu = number, memory = string, replicas = number })
  default     = { cpu = 0.25, memory = "0.5Gi", replicas = 2 }
}

variable "embedding" {
  description = "Embedding app size. One replica always runs."
  type        = object({ cpu = number, memory = string })
  default     = { cpu = 2, memory = "4Gi" }
}

variable "migrate_job" {
  description = "migrate job size."
  type        = object({ cpu = number, memory = string })
  default     = { cpu = 0.5, memory = "1Gi" }
}

variable "pipeline_job" {
  description = "pipeline job size. 4 vCPU and 8Gi is the Consumption profile's largest."
  type        = object({ cpu = number, memory = string })
  default     = { cpu = 4, memory = "8Gi" }
}

variable "pipeline_timeout_hours" {
  description = "Longest a pipeline job may run before Container Apps stops it."
  type        = number
  default     = 12
}

variable "db_sku" {
  description = "PostgreSQL flexible server size."
  type        = string
  default     = "GP_Standard_D2ds_v5"
}

variable "db_storage_mb" {
  description = "PostgreSQL storage, in MB (one of the sizes Azure offers, such as 32768 or 131072)."
  type        = number
  default     = 131072
}

variable "db_high_availability" {
  description = "Keep a standby database in a second availability zone. Not available on the Burstable sizes."
  type        = bool
  default     = true
}

variable "db_backup_retention_days" {
  description = "Days of automated database backups, 7 to 35."
  type        = number
  default     = 7
}

variable "redis_sku" {
  description = "Azure Managed Redis size."
  type        = string
  default     = "Balanced_B0"
}

variable "redis_high_availability" {
  description = "Keep a Redis replica. It only holds rate-limit counts, which are rebuilt if lost."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "Days to keep container logs, 30 to 730."
  type        = number
  default     = 30
}

variable "provider_secrets" {
  description = "Keys for model providers other than this deployment's Azure AI Foundry models, by setting name, for example { HUGGINGFACE_API_KEY = \"...\" }. They become Container Apps secrets, and are kept in Terraform's state."
  type        = map(string)
  default     = {}
  sensitive   = true
}
