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
  description = "Tag of evidencelab_image to run, for example 1.6.5, 1.6.6-rc.1 or main."
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

variable "customize_assets_dir" {
  description = "Folder of your own branding for the web app (theme.css, logo, favicon, footer, fonts), relative to deploy/aws; see docs/admin/customization.md. Saved with the deployment, so every web app build uses it. Empty: the CUSTOMIZE_ASSETS environment variable if set, otherwise the stock customize/ folder."
  type        = string
  default     = ""

  validation {
    condition     = var.customize_assets_dir == "" || length(fileset(var.customize_assets_dir, "**")) > 0
    error_message = "customize_assets_dir must be empty, or a folder that holds at least one file."
  }
}

variable "services_enabled" {
  description = "Run the ui, api, mcp and embedding services. Leave false on the first apply, push the web app image and run the migrate task, then set true."
  type        = bool
  default     = false
}

variable "domain_name" {
  description = "Domain for the site, for example evidencelab.example.org. Empty serves the site on CloudFront's own HTTPS address with cloudfront_enabled, or otherwise on the load balancer's own address over plain HTTP, for testing only."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone for domain_name. Used to validate the HTTPS certificate and to point the domain at CloudFront or the load balancer."
  type        = string
  default     = ""
}

variable "cloudfront_enabled" {
  description = "Serve the site through CloudFront with an AWS WAF web ACL. The load balancer then moves to the private subnets and only CloudFront can reach it, and the site is HTTPS even without domain_name."
  type        = bool
  default     = false
}

variable "cloudfront_price_class" {
  description = "Edge locations CloudFront serves from: PriceClass_100 (the United States, Canada, Mexico, Europe, Israel and Türkiye; the cheapest), PriceClass_200 (adds Asia, the Middle East and Africa) or PriceClass_All (adds South America, Australia and New Zealand)."
  type        = string
  default     = "PriceClass_100"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.cloudfront_price_class)
    error_message = "cloudfront_price_class must be PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}

variable "cloudfront_origin_read_timeout" {
  description = "Seconds CloudFront waits for a response to start, and between the parts of a streamed one. Chat answers send a heartbeat every 15 seconds; AI summaries send nothing between their first event and the model's first words. Above 60 needs a CloudFront quota increase first."
  type        = number
  default     = 60

  validation {
    condition     = var.cloudfront_origin_read_timeout >= 1 && var.cloudfront_origin_read_timeout <= 180
    error_message = "cloudfront_origin_read_timeout must be between 1 and 180 seconds."
  }
}

variable "waf_allowed_ip_ranges" {
  description = "With cloudfront_enabled, the only addresses (CIDR ranges, IPv4 or IPv6) that may reach the site, for example an organisation's office and VPN ranges. Empty lets every address through to the other rules."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.waf_allowed_ip_ranges : can(cidrhost(c, 0))])
    error_message = "Every waf_allowed_ip_ranges entry must be a CIDR range, for example 203.0.113.0/24."
  }
}

variable "waf_rate_limit" {
  description = "With cloudfront_enabled, requests one address may make in 5 minutes before AWS WAF blocks it until its rate drops. Visitors behind one office or VPN address share it. 0 turns the rule off."
  type        = number
  default     = 2000

  validation {
    condition     = var.waf_rate_limit == 0 || var.waf_rate_limit >= 10
    error_message = "waf_rate_limit must be 0 (off) or at least 10."
  }
}

variable "waf_core_rules_to_count" {
  description = "Rules in AWS's core rule set (AWSManagedRulesCommonRuleSet) that count matching requests instead of blocking them. SizeRestrictions_BODY blocks request bodies over 8 KB, and Evidence Lab accepts bodies up to 2 MB (MAX_REQUEST_BODY_BYTES). SizeRestrictions_QUERYSTRING blocks query strings over 2,048 bytes, and Microsoft sign-in sends visitors back to /api/auth/microsoft/callback with a longer one, so while it blocks no Microsoft sign-in can finish. A list you set replaces this one: keep both unless you have another way to let those requests through. null means the default."
  type        = list(string)
  default     = ["SizeRestrictions_BODY", "SizeRestrictions_QUERYSTRING"]
  nullable    = false
}

variable "waf_count_only" {
  description = "Run every AWS WAF rule in count mode: WAF records what each rule would have blocked, in CloudWatch metrics and sampled requests, and blocks nothing. For the first days of a new site; check the matches, then set false."
  type        = bool
  default     = false
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

variable "restore_task" {
  description = "restore task size (scripts/restore-data.sh): loads a Postgres export and a data archive."
  type        = object({ cpu = number, memory = number })
  default     = { cpu = 1024, memory = 4096 }
}

variable "transfer_retention_days" {
  description = "Days an upload stays in the transfer bucket (transfer.tf) before S3 deletes it."
  type        = number
  default     = 30

  validation {
    condition     = var.transfer_retention_days >= 1
    error_message = "transfer_retention_days must be at least 1."
  }
}

variable "pipeline_files_dir" {
  description = "Folder of your own pipeline files (for example a data source's downloader script and the spreadsheet it reads), relative to deploy/aws. They are copied into the pipeline task at /app/custom before each run, so a data source's download command can name /app/custom/<file>. Empty: none."
  type        = string
  default     = ""

  validation {
    condition     = var.pipeline_files_dir == "" || length(fileset(var.pipeline_files_dir, "**")) > 0
    error_message = "pipeline_files_dir must be empty, or a folder that holds at least one file."
  }
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

variable "db_engine_version" {
  description = "PostgreSQL major version for a new database, such as 17. It starts on that version's default minor version; an existing database keeps its version (see data.tf)."
  type        = string
  default     = "17"

  validation {
    condition     = can(regex("^[0-9]{2}$", var.db_engine_version))
    error_message = "db_engine_version is a major version only, such as \"17\"."
  }
}

variable "db_backup_retention_days" {
  description = "Days of automated database backups."
  type        = number
  default     = 7
}

variable "backups_enabled" {
  description = "Scheduled AWS Backup backups of Postgres, the EFS documents and Qdrant's instance (backup.tf). False turns them off."
  type        = bool
  default     = true
}

variable "backup_schedule" {
  description = "When the scheduled backups run, as an AWS Backup cron expression in UTC. The default is every Sunday at 03:00."
  type        = string
  default     = "cron(0 3 ? * SUN *)"

  validation {
    condition     = can(regex("^cron\\(.+\\)$", var.backup_schedule))
    error_message = "backup_schedule must be an AWS Backup cron expression, for example cron(0 3 ? * SUN *)."
  }
}

variable "backup_retention_days" {
  description = "Days each scheduled backup is kept."
  type        = number
  default     = 35

  validation {
    condition     = var.backup_retention_days >= 1
    error_message = "backup_retention_days must be at least 1."
  }
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

variable "alert_emails" {
  description = "Addresses that get the deployment's alerts by email, such as bedrock_alarms. They are subscribed to an SNS topic named <name>-alerts in each region an alarm watches, and each address must click \"Confirm subscription\" in AWS's first email from each one. Empty sends no alerts."
  type        = list(string)
  default     = []
  nullable    = false

  validation {
    condition     = alltrue([for e in var.alert_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "Every alert_emails entry must be an email address."
  }
}

variable "bedrock_alarms" {
  description = "Email alerts on Amazon Bedrock use, keyed by the model's ModelId as CloudWatch shows it (aws cloudwatch list-metrics --namespace AWS/Bedrock; an inference profile shows as its own ID, such as us.amazon.nova-2-lite-v1:0). Each sets one or more levels for a rolling hour: input_tokens_per_hour, output_tokens_per_hour, invocations_per_hour. region is where the model is called, if not the deployment's region (rerank models are offered in only some). Base the levels on the busiest hour of normal use. Needs alert_emails. Empty sets no alarms."
  type = map(object({
    region                 = optional(string)
    input_tokens_per_hour  = optional(number)
    output_tokens_per_hour = optional(number)
    invocations_per_hour   = optional(number)
  }))
  default  = {}
  nullable = false

  validation {
    condition = alltrue([
      for a in values(var.bedrock_alarms) :
      anytrue([a.input_tokens_per_hour != null, a.output_tokens_per_hour != null, a.invocations_per_hour != null])
    ])
    error_message = "Every bedrock_alarms entry must set at least one of input_tokens_per_hour, output_tokens_per_hour and invocations_per_hour."
  }

  validation {
    condition = alltrue(flatten([
      for a in values(var.bedrock_alarms) : [
        for v in [a.input_tokens_per_hour, a.output_tokens_per_hour, a.invocations_per_hour] : v == null ? true : v > 0
      ]
    ]))
    error_message = "bedrock_alarms levels must be greater than 0."
  }

  validation {
    condition     = length(var.bedrock_alarms) == 0 || length(var.alert_emails) > 0
    error_message = "bedrock_alarms needs at least one address in alert_emails, or no one would hear of them."
  }
}

variable "bedrock_call_log" {
  description = "Amazon Bedrock's call log (bedrock_logging.tf): in each region the app calls Bedrock in, every call's caller, model and token counts go to the log group /aws/bedrock/<name>/model-invocations, without the text of prompts and answers. It is a setting of the whole AWS account in each region, so it records every caller, and only one deployment in an account should turn it on. false: off."
  type        = bool
  default     = true
  nullable    = false
}

variable "bedrock_call_log_retention_days" {
  description = "Days to keep the Bedrock call log."
  type        = number
  default     = 365
  nullable    = false

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.bedrock_call_log_retention_days)
    error_message = "bedrock_call_log_retention_days must be one CloudWatch Logs offers: 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288 or 3653."
  }
}
