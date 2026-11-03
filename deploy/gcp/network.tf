# The APIs the deployment uses, and its network: one VPC with a subnet for the
# Cloud Run services and jobs and for Qdrant, a private connection for Cloud
# SQL and Memorystore, and Cloud NAT for outbound internet access. Nothing in
# the network has a public address of its own.

locals {
  # Enabling an API is a project setting that stays after the deployment is
  # removed, so teardown leaves them enabled.
  apis = [
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "dns.googleapis.com",
    "discoveryengine.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
  ]
  subnet_cidr = "10.0.0.0/20"
}

resource "google_project_service" "this" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "main" {
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.this]
}

# Cloud Run reaches the network through this subnet (Direct VPC egress).
# Private Google Access lets it call Google's APIs and the embedding
# service's internal address without leaving Google's network.
resource "google_compute_subnetwork" "main" {
  name                     = var.name
  network                  = google_compute_network.main.id
  ip_cidr_range            = local.subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_router" "main" {
  name    = var.name
  network = google_compute_network.main.id
}

resource "google_compute_router_nat" "main" {
  name                               = var.name
  router                             = google_compute_router.main.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# Cloud SQL and Memorystore get private addresses from this range, through
# Google's private services connection to the network.
resource "google_compute_global_address" "services" {
  name          = "${var.name}-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.main.id
}

resource "google_service_networking_connection" "services" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.services.name]

  # Cloud SQL keeps hold of the connection for a while after its instance is
  # deleted, so a plain delete fails at teardown. Terraform deletes Cloud SQL
  # and Memorystore first, so removing the peering then is safe.
  deletion_policy = "REMOVE_PEERING"
}

# Only the subnet reaches Qdrant. With no other rule, Google refuses inbound
# traffic from the internet.
resource "google_compute_firewall" "qdrant" {
  name          = "${var.name}-qdrant"
  network       = google_compute_network.main.id
  direction     = "INGRESS"
  source_ranges = [local.subnet_cidr]
  target_tags   = ["${var.name}-qdrant"]

  allow {
    protocol = "tcp"
    ports    = ["6333"]
  }
}
