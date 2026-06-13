# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

data "juju_model" "this" {
  name = var.model
}

resource "juju_application" "snuba" {
  name               = var.app_name
  model_uuid         = data.juju_model.this.uuid
  units              = var.units
  constraints        = var.constraints
  config             = var.config
  storage_directives = var.storage

  charm {
    name     = "sentry-snuba-k8s"
    channel  = var.channel
    revision = var.revision
    base     = "ubuntu@24.04"
  }

  trust = true
}
