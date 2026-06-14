# Reference: configuration, integrations and actions

This page documents every config option, integration endpoint and action for
the four `sentry-operators` charms, as declared in their `charmcraft.yaml`.

## Configuration options

### `sentry-k8s`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `feature-complete` | boolean | `true` | Run the full feature set (transactions, metrics, profiling, replays, crons, uptime, feedback, issue platform) as well as error tracking. Disable for a smaller errors-only deployment. |
| `event-retention-days` | int | `90` | How long event data is retained, in days. The charm prunes data older than this once a day (self-hosted Sentry has no built-in scheduler for it). |
| `taskworker-concurrency` | int | `4` | Number of concurrent task worker processes. |
| `enable-symbolicator` | boolean | `true` | Run the symbolicator service for native/JS stack-trace symbolication. |
| `smtp-host` | string | `""` | SMTP relay host for outbound email. Empty disables email. |
| `smtp-port` | int | `587` | SMTP relay port. |
| `smtp-username` | string | `""` | SMTP username. |
| `smtp-password` | string | `""` | SMTP password. |
| `smtp-use-tls` | boolean | `true` | Use STARTTLS for SMTP. |
| `mail-from` | string | `sentry@localhost` | From-address for outbound email. |

### `sentry-snuba-k8s`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `feature-complete` | boolean | `true` | Run the full set of Snuba consumers (transactions, metrics, generic-metrics, profiling, replays, issue platform, events-analytics-platform) as well as the always-on errors set. Disable for an errors-only deployment. |
| `event-retention-days` | int | `90` | How long event data is retained, in days. Must match the Sentry application's retention so ClickHouse TTLs line up. |

### `sentry-relay-k8s`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `log-level` | string | `info` | Relay's log level: one of `trace`, `debug`, `info`, `warn`, `error`. |

### `clickhouse-k8s`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `max-memory-usage-ratio` | float | `0.3` | Fraction of the unit's RAM ClickHouse may use (`max_server_memory_usage_to_ram_ratio`). Lower on small units. |
| `log-level` | string | `warning` | ClickHouse server log level: one of `none`, `fatal`, `error`, `warning`, `information`, `debug`, `trace`. |

## Integration endpoints

Endpoint names are what you pass to `juju integrate <app>:<endpoint>`. The
interface name must match on both ends of a relation.

### `sentry-k8s`

| Endpoint | Role | Interface | Required | Notes |
|----------|------|-----------|----------|-------|
| `database` | requires | `postgresql_client` | yes | Sentry metadata in PostgreSQL. |
| `kafka` | requires | `kafka_client` | yes | Event spine. |
| `redis` | requires | `redis` | yes | Cache, buffers, quotas, queues. |
| `snuba` | requires | `sentry_snuba` | yes | Snuba HTTP API. |
| `ingress` | requires | `ingress` | no | Traefik ingress for the web UI/API. |
| `logging` | requires | `loki_push_api` | no | Push logs to Loki. |
| `sentry-relay` | provides | `sentry_relay` | no | Web upstream + secret key for Relay. |
| `metrics-endpoint` | provides | `prometheus_scrape` | no | Prometheus scrape target. |
| `grafana-dashboard` | provides | `grafana_dashboard` | no | Grafana dashboards. |
| `sentry-peers` | peers | `sentry_peers` | — | Peer relation (secret-key, leadership state). |

### `sentry-snuba-k8s`

| Endpoint | Role | Interface | Required | Notes |
|----------|------|-----------|----------|-------|
| `clickhouse` | requires | `sentry_clickhouse` | yes | ClickHouse connection details. |
| `kafka` | requires | `kafka_client` | yes | Event spine. |
| `redis` | requires | `redis` | yes | Snuba state. |
| `logging` | requires | `loki_push_api` | no | Push logs to Loki. |
| `snuba` | provides | `sentry_snuba` | yes | Snuba HTTP API URL for Sentry. |
| `metrics-endpoint` | provides | `prometheus_scrape` | no | Prometheus scrape target. |
| `grafana-dashboard` | provides | `grafana_dashboard` | no | Grafana dashboards. |
| `snuba-peers` | peers | `snuba_peers` | — | Peer relation. |

### `sentry-relay-k8s`

| Endpoint | Role | Interface | Required | Notes |
|----------|------|-----------|----------|-------|
| `kafka` | requires | `kafka_client` | yes | Forwards events to Kafka. |
| `redis` | requires | `redis` | yes | Project configs, rate-limit counters. |
| `sentry` | requires | `sentry_relay` | yes | Registers against the Sentry upstream. |
| `ingress` | requires | `ingress` | no | Traefik ingress for event intake. |
| `logging` | requires | `loki_push_api` | no | Push logs to Loki. |
| `metrics-endpoint` | provides | `prometheus_scrape` | no | Prometheus scrape target. |
| `grafana-dashboard` | provides | `grafana_dashboard` | no | Grafana dashboards. |
| `relay-peers` | peers | `relay_peers` | — | Peer relation. |

### `clickhouse-k8s`

| Endpoint | Role | Interface | Required | Notes |
|----------|------|-----------|----------|-------|
| `clickhouse` | provides | `sentry_clickhouse` | yes | Connection details for Snuba. |
| `metrics-endpoint` | provides | `prometheus_scrape` | no | Prometheus scrape target. |
| `grafana-dashboard` | provides | `grafana_dashboard` | no | Grafana dashboards. |
| `logging` | requires | `loki_push_api` | no | Push logs to Loki. |
| `clickhouse-peers` | peers | `clickhouse_peers` | — | Peer relation. |

## Actions

### `sentry-k8s`

| Action | Parameters | Description |
|--------|------------|-------------|
| `create-admin` | `email` (string, **required**), `password` (string, optional) | Create a Sentry superuser. If `password` is omitted a random one is generated. The password is written to a Juju secret whose id is returned. |
| `get-admin-password` | `email` (string, **required**) | Return the id of the Juju secret holding a previously created admin's credentials. |
| `pause` | — | Stop Sentry's web, workers and consumers for maintenance. Kafka retains events; the pause survives reconcile until `resume`. |
| `resume` | — | Restart the Sentry services after a `pause`. |

```bash
juju run sentry-k8s/leader create-admin email=admin@example.com
juju show-secret --reveal <returned-secret-id>

# Drain for maintenance, then bring the workload back.
juju run sentry-k8s/leader pause
juju run sentry-k8s/leader resume
```

The other three charms (`sentry-snuba-k8s`, `sentry-relay-k8s`,
`clickhouse-k8s`) declare no actions.
