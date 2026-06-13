# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# Product / solution module: composes the four sentry-operators charm modules
# with the Canonical data and ingress charms, and wires every integration.

# ---------------------------------------------------------------------------
# The sentry-operators charms (this repo), via their per-charm modules.
# ---------------------------------------------------------------------------

module "clickhouse" {
  source  = "../charms/clickhouse-k8s/terraform"
  model   = var.model
  channel = var.clickhouse_channel
}

module "snuba" {
  source  = "../charms/sentry-snuba-k8s/terraform"
  model   = var.model
  channel = var.snuba_channel
  config = {
    feature-complete     = tostring(var.feature_complete)
    event-retention-days = tostring(var.event_retention_days)
  }
}

module "relay" {
  source  = "../charms/sentry-relay-k8s/terraform"
  model   = var.model
  channel = var.relay_channel
}

module "sentry" {
  source  = "../charms/sentry-k8s/terraform"
  model   = var.model
  channel = var.sentry_channel
  config = {
    feature-complete     = tostring(var.feature_complete)
    event-retention-days = tostring(var.event_retention_days)
  }
}

# ---------------------------------------------------------------------------
# Related data + ingress charms (Canonical), deployed directly from Charmhub.
# ---------------------------------------------------------------------------

resource "juju_application" "postgresql" {
  name  = "postgresql-k8s"
  model = var.model
  units = 1
  trust = true

  charm {
    name    = "postgresql-k8s"
    channel = var.postgresql_channel
    base    = "ubuntu@22.04"
  }

  config = {
    # Sentry requires the citext and pg_trgm extensions.
    plugin_citext_enable  = "true"
    plugin_pg_trgm_enable = "true"
  }
}

resource "juju_application" "redis" {
  name  = "redis-k8s"
  model = var.model
  units = 1
  trust = true

  charm {
    name    = "redis-k8s"
    channel = var.redis_channel
    base    = "ubuntu@22.04"
  }
}

resource "juju_application" "kafka" {
  name  = "kafka-k8s"
  model = var.model
  units = 1
  trust = true

  charm {
    name    = "kafka-k8s"
    channel = var.kafka_channel
    base    = "ubuntu@22.04"
  }

  config = {
    roles = "broker,controller"
  }
}

resource "juju_application" "traefik" {
  name  = "traefik-k8s"
  model = var.model
  units = 1
  trust = true

  charm {
    name    = "traefik-k8s"
    channel = var.traefik_channel
    base    = "ubuntu@20.04"
  }
}

# ---------------------------------------------------------------------------
# Integrations.
# ---------------------------------------------------------------------------

# --- Snuba -> ClickHouse / Kafka / Redis ---

resource "juju_integration" "snuba_clickhouse" {
  model = var.model

  application {
    name     = module.snuba.app_name
    endpoint = module.snuba.requires.clickhouse
  }
  application {
    name     = module.clickhouse.app_name
    endpoint = module.clickhouse.provides.clickhouse
  }
}

resource "juju_integration" "snuba_kafka" {
  model = var.model

  application {
    name     = module.snuba.app_name
    endpoint = module.snuba.requires.kafka
  }
  application {
    name     = juju_application.kafka.name
    endpoint = "kafka-client"
  }
}

resource "juju_integration" "snuba_redis" {
  model = var.model

  application {
    name     = module.snuba.app_name
    endpoint = module.snuba.requires.redis
  }
  application {
    name     = juju_application.redis.name
    endpoint = "redis"
  }
}

# --- Sentry -> Postgres / Kafka / Redis / Snuba ---

resource "juju_integration" "sentry_postgresql" {
  model = var.model

  application {
    name     = module.sentry.app_name
    endpoint = module.sentry.requires.database
  }
  application {
    name     = juju_application.postgresql.name
    endpoint = "database"
  }
}

resource "juju_integration" "sentry_kafka" {
  model = var.model

  application {
    name     = module.sentry.app_name
    endpoint = module.sentry.requires.kafka
  }
  application {
    name     = juju_application.kafka.name
    endpoint = "kafka-client"
  }
}

resource "juju_integration" "sentry_redis" {
  model = var.model

  application {
    name     = module.sentry.app_name
    endpoint = module.sentry.requires.redis
  }
  application {
    name     = juju_application.redis.name
    endpoint = "redis"
  }
}

resource "juju_integration" "sentry_snuba" {
  model = var.model

  application {
    name     = module.sentry.app_name
    endpoint = module.sentry.requires.snuba
  }
  application {
    name     = module.snuba.app_name
    endpoint = module.snuba.provides.snuba
  }
}

# --- Relay -> Kafka / Redis / Sentry ---

resource "juju_integration" "relay_kafka" {
  model = var.model

  application {
    name     = module.relay.app_name
    endpoint = module.relay.requires.kafka
  }
  application {
    name     = juju_application.kafka.name
    endpoint = "kafka-client"
  }
}

resource "juju_integration" "relay_redis" {
  model = var.model

  application {
    name     = module.relay.app_name
    endpoint = module.relay.requires.redis
  }
  application {
    name     = juju_application.redis.name
    endpoint = "redis"
  }
}

resource "juju_integration" "relay_sentry" {
  model = var.model

  application {
    name     = module.relay.app_name
    endpoint = module.relay.requires.sentry
  }
  application {
    name     = module.sentry.app_name
    endpoint = module.sentry.provides.sentry_relay
  }
}

# --- Ingress: traefik -> Sentry and Relay ---

resource "juju_integration" "sentry_ingress" {
  model = var.model

  application {
    name     = module.sentry.app_name
    endpoint = module.sentry.requires.ingress
  }
  application {
    name     = juju_application.traefik.name
    endpoint = "ingress"
  }
}

resource "juju_integration" "relay_ingress" {
  model = var.model

  application {
    name     = module.relay.app_name
    endpoint = module.relay.requires.ingress
  }
  application {
    name     = juju_application.traefik.name
    endpoint = "ingress"
  }
}
