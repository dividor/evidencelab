terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.8"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Bill API calls to this project, which a personal gcloud login otherwise
  # leaves unset.
  billing_project       = var.project_id
  user_project_override = true

  # Every resource that takes labels carries the deployment name.
  default_labels = {
    deployment = var.name
  }
}
