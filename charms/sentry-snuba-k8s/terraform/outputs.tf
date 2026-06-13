# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

output "app_name" {
  description = "The deployed application name."
  value       = juju_application.snuba.name
}

output "provides" {
  description = "Integration endpoints this charm provides."
  value = {
    snuba             = "snuba"
    metrics_endpoint  = "metrics-endpoint"
    grafana_dashboard = "grafana-dashboard"
  }
}

output "requires" {
  description = "Integration endpoints this charm requires."
  value = {
    clickhouse = "clickhouse"
    kafka      = "kafka"
    redis      = "redis"
    logging    = "logging"
  }
}
