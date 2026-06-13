# clickhouse-k8s

A [Juju](https://juju.is) charm that runs a single-node
[ClickHouse](https://clickhouse.com) server for self-hosted Sentry's
[Snuba](https://github.com/getsentry/snuba) analytics service, on Kubernetes.

This charm is part of the [`sentry-operators`](https://github.com/tonyandrewmeyer/sentry-operators)
charm set. It is **not** a general-purpose ClickHouse charm: it is tuned for
Snuba, which bootstraps and migrates its own schema over the wire.

## Usage

```bash
juju deploy clickhouse-k8s --channel latest/edge
juju integrate clickhouse-k8s sentry-snuba-k8s
```

ClickHouse stores the event analytics data on a Juju storage volume (`data`,
default 10 GiB; size it to your retention and event volume).

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `max-memory-usage-ratio` | `0.3` | Fraction of the unit's RAM ClickHouse may use. |
| `log-level` | `warning` | Server log level. |

## Integrations

- **`clickhouse`** (`sentry_clickhouse`, provides): hands Snuba the host, ports
  and credentials.
- **`metrics-endpoint`**, **`grafana-dashboard`** (provides),
  **`logging`** (requires): integrate with the
  [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

## Security

See the repository [`SECURITY.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/SECURITY.md).

## Contributing

See [`CONTRIBUTING.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/CONTRIBUTING.md)
and the [design doc](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/docs/design.md).
Licensed under [Apache-2.0](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/LICENSE).
