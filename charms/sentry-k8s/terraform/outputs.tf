# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

output "app_name" {
  description = "The deployed application name."
  value       = juju_application.sentry.name
}

output "provides" {
  description = "Integration endpoints this charm provides."
  value = {
    sentry_relay      = "sentry-relay"
    metrics_endpoint  = "metrics-endpoint"
    grafana_dashboard = "grafana-dashboard"
  }
}

output "requires" {
  description = "Integration endpoints this charm requires."
  value = {
    database = "database"
    kafka    = "kafka"
    redis    = "redis"
    snuba    = "snuba"
    ingress  = "ingress"
    logging  = "logging"
  }
}
