terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region

  # Every resource carries the deployment name, so anything left behind can be
  # found with: aws resourcegroupstaggingapi get-resources --tag-filters Key=Deployment,Values=<name>
  default_tags {
    tags = {
      Deployment = var.name
    }
  }
}
