# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

output "model" {
  description = "The Juju model the product is deployed into."
  value       = var.model
}

output "app_names" {
  description = "The deployed application names, by role."
  value = {
    sentry     = module.sentry.app_name
    snuba      = module.snuba.app_name
    relay      = module.relay.app_name
    clickhouse = module.clickhouse.app_name
    postgresql = juju_application.postgresql.name
    redis      = juju_application.redis.name
    kafka      = juju_application.kafka.name
    traefik    = juju_application.traefik.name
  }
}
