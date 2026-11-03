# The resource group that holds the whole deployment, and its network: one
# virtual network with a subnet for the Container Apps environment, one for
# Postgres, and one for Qdrant and the private endpoints. A NAT gateway gives
# the apps and Qdrant their outbound internet access (image pulls and model
# calls); nothing in the network has a public address of its own.

resource "random_string" "suffix" {
  # Storage, registry, Postgres, Redis and Foundry names are global, so each
  # deployment adds a suffix of its own.
  length  = 6
  upper   = false
  special = false
}

locals {
  tags         = { Deployment = var.name }
  vnet_cidr    = "10.0.0.0/16"
  compact_name = substr(replace(var.name, "-", ""), 0, 18)
  unique_name  = "${var.name}-${random_string.suffix.result}"
}

resource "azurerm_resource_group" "main" {
  name     = var.name
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "main" {
  name                = "${var.name}-vnet"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = [local.vnet_cidr]
  tags                = local.tags
}

# The Container Apps environment needs a /27 or larger subnet of its own,
# delegated to it. The storage service endpoint lets the file share accept
# the apps' connections while refusing everything else.
resource "azurerm_subnet" "apps" {
  name                 = "apps"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.0.0/23"]

  service_endpoint {
    service = "Microsoft.Storage"
  }

  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.2.0/24"]

  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "data" {
  name                 = "data"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.3.0/24"]
}

resource "azurerm_public_ip" "nat" {
  name                = "${var.name}-nat"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_nat_gateway" "main" {
  name                = "${var.name}-nat"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku_name            = "Standard"
  tags                = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "main" {
  nat_gateway_id       = azurerm_nat_gateway.main.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

resource "azurerm_subnet_nat_gateway_association" "this" {
  for_each = {
    apps = azurerm_subnet.apps.id
    data = azurerm_subnet.data.id
  }
  subnet_id      = each.value
  nat_gateway_id = azurerm_nat_gateway.main.id
}

# Only the apps reach Qdrant. Azure's default rules already refuse inbound
# traffic from the internet.
resource "azurerm_network_security_group" "data" {
  name                = "${var.name}-data"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  security_rule {
    name                       = "qdrant-from-apps"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = azurerm_subnet.apps.address_prefixes[0]
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "6333"
  }

  security_rule {
    name                       = "deny-other-network-traffic"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_address_prefix      = "VirtualNetwork"
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "data" {
  subnet_id                 = azurerm_subnet.data.id
  network_security_group_id = azurerm_network_security_group.data.id
}

# Private names for Postgres and Redis, resolved only inside the network.
resource "azurerm_private_dns_zone" "this" {
  for_each = {
    postgres = "${var.name}.private.postgres.database.azure.com"
    redis    = "privatelink.redis.azure.net"
  }
  name                = each.value
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "this" {
  for_each            = azurerm_private_dns_zone.this
  name                = each.key
  private_dns_zone_id = each.value.id
  virtual_network_id  = azurerm_virtual_network.main.id
  tags                = local.tags
}
