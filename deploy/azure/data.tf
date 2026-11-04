# Postgres, Redis, the file share, Qdrant, the generated keys, the web app
# image registry and the Azure AI Foundry models.

resource "random_password" "postgres" {
  length  = 40
  special = false
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                          = local.unique_name
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "16"
  sku_name                      = var.db_sku
  storage_mb                    = var.db_storage_mb
  backup_retention_days         = var.db_backup_retention_days
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.this["postgres"].id
  public_network_access_enabled = false
  administrator_login           = "evidencelab"
  administrator_password        = random_password.postgres.result
  tags                          = local.tags

  # Azure chooses the zones, from those with capacity for the size.
  dynamic "high_availability" {
    for_each = var.db_high_availability ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.this]

  lifecycle {
    # Azure may move the primary to the standby's zone after a failover.
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
}

# The migrations create the vector and pg_trgm extensions, which Azure only
# allows once they are listed here.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "VECTOR,PG_TRGM"
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "evidencelab"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Redis holds the rate-limit counts that every api and mcp replica shares.
# It is reached through a private endpoint, over TLS.
resource "azurerm_managed_redis" "main" {
  name                      = local.unique_name
  resource_group_name       = azurerm_resource_group.main.name
  location                  = azurerm_resource_group.main.location
  sku_name                  = var.redis_sku
  high_availability_enabled = var.redis_high_availability
  public_network_access     = "Disabled"
  tags                      = local.tags

  default_database {
    # The rate limiter's Redis client does not follow cluster redirects.
    clustering_policy                  = "NoCluster"
    access_keys_authentication_enabled = true
  }
}

resource "azurerm_private_endpoint" "redis" {
  name                = "${var.name}-redis"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  subnet_id           = azurerm_subnet.data.id
  tags                = local.tags

  private_service_connection {
    name                           = "redis"
    private_connection_resource_id = azurerm_managed_redis.main.id
    subresource_names              = ["redisEnterprise"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "redis"
    private_dns_zone_ids = [azurerm_private_dns_zone.this["redis"].id]
  }
}

# Documents and page images, mounted at /app/data in every app and job. The
# share only accepts connections from the apps' subnet.
resource "azurerm_storage_account" "data" {
  name                            = "${local.compact_name}${random_string.suffix.result}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.tags

  network_rules {
    default_action             = "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [azurerm_subnet.apps.id]
  }
}

resource "azurerm_storage_share" "data" {
  name               = "data"
  storage_account_id = azurerm_storage_account.data.id
  quota              = 100
}

# Qdrant needs block storage, which Container Apps does not offer, so it runs
# on a small virtual machine of its own, with no public address.
locals {
  qdrant_on_vm = var.qdrant_url == ""
  qdrant_url   = local.qdrant_on_vm ? "http://${azurerm_network_interface.qdrant[0].private_ip_address}:6333" : var.qdrant_url
  qdrant_key   = local.qdrant_on_vm ? random_password.qdrant_api_key.result : var.qdrant_api_key
  qdrant_image = "qdrant/qdrant:v1.18.3"
}

resource "random_password" "qdrant_api_key" {
  length  = 40
  special = false
}

# Azure requires a sign-in key for a Linux virtual machine. Nothing uses it:
# the machine has no public address and no inbound rule for SSH.
resource "tls_private_key" "qdrant" {
  count     = local.qdrant_on_vm ? 1 : 0
  algorithm = "ED25519"
}

resource "azurerm_network_interface" "qdrant" {
  count               = local.qdrant_on_vm ? 1 : 0
  name                = "${var.name}-qdrant"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.data.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_linux_virtual_machine" "qdrant" {
  count                 = local.qdrant_on_vm ? 1 : 0
  name                  = "${var.name}-qdrant"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  size                  = var.qdrant_vm_size
  admin_username        = "evidencelab"
  network_interface_ids = [azurerm_network_interface.qdrant[0].id]
  tags                  = local.tags

  admin_ssh_key {
    username   = "evidencelab"
    public_key = tls_private_key.qdrant[0].public_key_openssh
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = var.qdrant_disk_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  # Docker runs Qdrant with its storage on the machine's disk, restarting it
  # with the machine. Changing the key or image replaces the machine.
  custom_data = base64encode(<<-EOT
    #!/bin/bash
    set -euo pipefail
    apt-get update
    apt-get install -y docker.io
    systemctl enable --now docker
    mkdir -p /var/lib/qdrant/storage
    docker run -d --name qdrant --restart always -p 6333:6333 \
      -v /var/lib/qdrant/storage:/qdrant/storage \
      -e QDRANT__SERVICE__API_KEY='${random_password.qdrant_api_key.result}' \
      ${local.qdrant_image}
  EOT
  )

  depends_on = [azurerm_subnet_nat_gateway_association.this]
}

# The keys the api signs and encrypts with. They live in Terraform's state
# and in the apps' secrets.
resource "random_password" "api_secret_key" {
  length  = 48
  special = false
}

resource "random_password" "auth_secret_key" {
  length  = 64
  special = false
}

# A Fernet key: 32 random bytes in URL-safe base64.
resource "random_bytes" "key_encryption_key" {
  length = 32
}

# The web app image, built and pushed for each deployment by
# scripts/build-ui-image.sh. The apps pull it with their managed identity.
resource "azurerm_container_registry" "main" {
  name                = "${local.compact_name}${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "apps" {
  name                = "${var.name}-apps"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "registry_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

# The models in config.json's "Azure Foundry" set, in a Foundry resource of
# the deployment's own. The containers call it with its key.
resource "azurerm_cognitive_account" "models" {
  name                  = local.unique_name
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = local.unique_name
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "this" {
  for_each             = var.model_deployments
  name                 = each.key
  cognitive_account_id = azurerm_cognitive_account.models.id

  model {
    format  = each.value.format
    name    = each.value.model
    version = each.value.version
  }

  sku {
    name     = each.value.sku
    capacity = each.value.capacity
  }
}
