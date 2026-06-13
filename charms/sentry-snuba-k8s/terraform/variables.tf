# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Application name in the Juju model."
  type        = string
  default     = "sentry-snuba-k8s"
}

variable "model" {
  description = "Name of the Juju model to deploy into."
  type        = string
}

variable "channel" {
  description = "Charmhub channel to deploy from."
  type        = string
  default     = "latest/edge"
}

variable "revision" {
  description = "Charm revision to deploy (null for the channel's latest)."
  type        = number
  default     = null
}

variable "units" {
  description = "Number of units."
  type        = number
  default     = 1
}

variable "constraints" {
  description = "Juju constraints for the application."
  type        = string
  default     = "arch=amd64 mem=4G"
}

variable "config" {
  description = "Charm configuration options."
  type        = map(string)
  default     = {}
}

variable "storage" {
  description = "Storage directives, e.g. { data = \"20G\" }."
  type        = map(string)
  default     = {}
}
