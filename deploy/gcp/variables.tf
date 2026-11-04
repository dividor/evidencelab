variable "project_id" {
  description = "Google Cloud project to deploy into, with billing linked. Use a project of its own: teardown removes everything this template made, and enabled APIs stay enabled."
  type        = string
}

variable "name" {
  description = "Deployment name. Prefixes and labels every resource, so several deployments can share a project."
  type        = string
  default     = "evidencelab"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,17}$", var.name))
    error_message = "name must be 2-18 lower-case letters, digits or hyphens, starting with a letter."
  }
}

variable "region" {
  description = "Region for everything. The Vertex AI models in config.json are called in vertex_location."
  type        = string
  default     = "us-central1"
}

variable "vertex_location" {
  description = "Vertex AI location the containers call the Gemini models in (GOOGLE_CLOUD_LOCATION). The Gemini 3 models are served from global: a new project got 404 for them from us-central1."
  type        = string
  default     = "global"
}

variable "evidencelab_image" {
  description = "Docker Hub image for the api, mcp, pipeline and migrate containers, without the tag. Cloud Run pulls it through the deployment's Docker Hub remote repository."
  type        = string
  default     = "astrobagel/evidencelab"
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
  description = "Docker Hub image for the embedding server, pulled the same way."
  type        = string
  default     = "michaelf34/infinity:0.0.70"
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
  description = "Create the web and embedding services. Leave false on the first apply, push the web app image and run the migrate job, then set true."
  type        = bool
  default     = false
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

variable "qdrant_machine_type" {
  description = "Machine type for Qdrant when qdrant_url is empty."
  type        = string
  default     = "e2-medium"
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

variable "provider_secrets" {
  description = "Keys for model providers other than Vertex AI, by setting name, for example { HUGGINGFACE_API_KEY = \"...\" }. They are stored in Secret Manager, and kept in Terraform's state."
  type        = map(string)
  default     = {}
  sensitive   = true
}

# Container sizes. Cloud Run takes CPU as a number of vCPUs and memory with a
# unit, for example "2" and "8Gi".

variable "web" {
  description = "Web service instances: each runs the ui, api and mcp containers together."
  type = object({
    min_instances = number
    max_instances = number
    ui            = object({ cpu = string, memory = string })
    api           = object({ cpu = string, memory = string })
    mcp           = object({ cpu = string, memory = string })
  })
  default = {
    min_instances = 2
    max_instances = 4
    ui            = { cpu = "1", memory = "512Mi" }
    api           = { cpu = "2", memory = "8Gi" }
    mcp           = { cpu = "1", memory = "2Gi" }
  }
}

variable "embedding" {
  description = "Embedding service size. One instance always runs. At 4Gi the server ran out of memory loading multilingual-e5-large (4,146 MiB used), so it gets 8Gi."
  type        = object({ cpu = string, memory = string })
  default     = { cpu = "2", memory = "8Gi" }
}

variable "migrate_job" {
  description = "migrate job size."
  type        = object({ cpu = string, memory = string })
  default     = { cpu = "1", memory = "1Gi" }
}

variable "pipeline_job" {
  description = "pipeline job size."
  type        = object({ cpu = string, memory = string })
  default     = { cpu = "4", memory = "16Gi" }
}

variable "pipeline_timeout_hours" {
  description = "Longest a pipeline job may run before Cloud Run stops it (at most 168)."
  type        = number
  default     = 12
}

variable "db_tier" {
  description = "Cloud SQL machine type."
  type        = string
  default     = "db-custom-2-8192"
}

variable "db_disk_gb" {
  description = "Cloud SQL storage, in GB."
  type        = number
  default     = 50
}

variable "db_high_availability" {
  description = "Keep a standby database in a second zone (REGIONAL availability)."
  type        = bool
  default     = true
}

variable "db_deletion_protection" {
  description = "Refuse to delete the database. Keep true for real data; set false for throwaway test deployments, or teardown stops at the database."
  type        = bool
  default     = true
}

variable "redis_memory_gb" {
  description = "Memorystore for Redis size, in GB."
  type        = number
  default     = 1
}

variable "redis_tier" {
  description = "Memorystore tier: STANDARD_HA keeps a replica, BASIC does not. Redis only holds rate-limit counts, which are rebuilt if lost."
  type        = string
  default     = "STANDARD_HA"
}
