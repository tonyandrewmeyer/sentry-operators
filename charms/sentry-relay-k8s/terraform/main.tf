# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

resource "juju_application" "relay" {
  name        = var.app_name
  model       = var.model
  units       = var.units
  constraints = var.constraints
  config      = var.config
  storage     = var.storage

  charm {
    name     = "sentry-relay-k8s"
    channel  = var.channel
    revision = var.revision
    base     = "ubuntu@24.04"
  }

  trust = true
}
