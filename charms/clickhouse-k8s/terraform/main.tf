# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

resource "juju_application" "clickhouse" {
  name        = var.app_name
  model       = var.model
  units       = var.units
  constraints = var.constraints
  config      = var.config
  storage     = var.storage

  charm {
    name     = "clickhouse-k8s"
    channel  = var.channel
    revision = var.revision
    base     = "ubuntu@24.04"
  }

  # ClickHouse holds the analytics data; let Juju own the trust so it can manage
  # the workload's Kubernetes resources.
  trust = true
}
