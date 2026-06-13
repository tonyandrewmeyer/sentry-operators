# sentry-snuba-k8s

A [Juju](https://juju.is) charm for [Snuba](https://github.com/getsentry/snuba),
the search and analytics service of self-hosted
[Sentry](https://develop.sentry.dev/self-hosted/), on Kubernetes.

Part of the [`sentry-operators`](https://github.com/tonyandrewmeyer/sentry-operators)
charm set. Snuba runs an HTTP query API plus a fleet of Kafka consumers that
stream event data into ClickHouse. This charm bootstraps the Kafka topics and
ClickHouse schema, and hands the Sentry charm the API URL.

## Usage

```bash
juju deploy sentry-snuba-k8s --channel latest/edge
juju deploy clickhouse-k8s --channel latest/edge
juju deploy kafka-k8s --channel 3/stable --config roles=broker,controller
juju deploy redis-k8s --channel latest/edge

juju integrate sentry-snuba-k8s clickhouse-k8s
juju integrate sentry-snuba-k8s kafka-k8s
juju integrate sentry-snuba-k8s redis-k8s
juju integrate sentry-snuba-k8s sentry-k8s
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `feature-complete` | `true` | Run the full consumer set (transactions, metrics, profiling, replays, issue platform, EAP) as well as the always-on errors set. |
| `event-retention-days` | `90` | Event retention; must match the Sentry application. |

## Integrations

- **`clickhouse`** (`sentry_clickhouse`), **`kafka`** (`kafka_client`),
  **`redis`** (`redis`) — required backends.
- **`snuba`** (`sentry_snuba`, provides) — hands Sentry the API URL.
- **`metrics-endpoint`**, **`grafana-dashboard`** (provides), **`logging`**
  (requires) — the Canonical Observability Stack.

When integrated with `kafka-k8s` (which authenticates clients with SASL/SCRAM),
the charm pushes a Snuba settings drop-in that adds the SASL credentials to the
broker config.

## Security

See the repository [`SECURITY.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/SECURITY.md).

## Contributing

See [`CONTRIBUTING.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/CONTRIBUTING.md).
Licensed under [Apache-2.0](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/LICENSE).
