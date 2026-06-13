# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

variable "model" {
  description = "Name of the Juju model to deploy the Sentry product into."
  type        = string
  default     = "sentry"
}

# --- Channels for the sentry-operators charms (this repo) ---

variable "sentry_channel" {
  description = "Charmhub channel for the sentry-k8s charm."
  type        = string
  default     = "latest/edge"
}

variable "snuba_channel" {
  description = "Charmhub channel for the sentry-snuba-k8s charm."
  type        = string
  default     = "latest/edge"
}

variable "relay_channel" {
  description = "Charmhub channel for the sentry-relay-k8s charm."
  type        = string
  default     = "latest/edge"
}

variable "clickhouse_channel" {
  description = "Charmhub channel for the clickhouse-k8s charm."
  type        = string
  default     = "latest/edge"
}

# --- Channels for the related data / ingress charms (Canonical) ---

variable "postgresql_channel" {
  description = "Charmhub channel for postgresql-k8s."
  type        = string
  default     = "14/stable"
}

variable "redis_channel" {
  description = "Charmhub channel for redis-k8s."
  type        = string
  default     = "latest/edge"
}

variable "kafka_channel" {
  description = "Charmhub channel for kafka-k8s."
  type        = string
  default     = "3/stable"
}

variable "traefik_channel" {
  description = "Charmhub channel for traefik-k8s."
  type        = string
  default     = "latest/stable"
}

# --- Behaviour ---

variable "feature_complete" {
  description = <<-EOT
    Run the full feature set (transactions, metrics, profiling, replays, crons,
    uptime, feedback). Set to false for a lighter errors-only deployment. This
    is applied to both sentry-k8s and sentry-snuba-k8s so they stay in step.
  EOT
  type        = bool
  default     = true
}

variable "event_retention_days" {
  description = "How long event data is retained, in days. Applied to sentry-k8s and sentry-snuba-k8s."
  type        = number
  default     = 90
}
