# sentry-relay-k8s

A [Juju](https://juju.is) charm for [Relay](https://github.com/getsentry/relay),
the event-intake proxy of self-hosted
[Sentry](https://develop.sentry.dev/self-hosted/), on Kubernetes.

Part of the [`sentry-operators`](https://github.com/tonyandrewmeyer/sentry-operators)
charm set. Relay runs in managed mode at the front of Sentry: it accepts events
from SDKs, normalises and rate-limits them, and forwards the processed events to
Kafka. It keeps a small amount of state in Redis and registers itself with the
Sentry web upstream using a keypair the charm stores in a Juju secret.

## Usage

```bash
juju deploy sentry-relay-k8s --channel latest/edge
juju deploy kafka-k8s --channel 3/stable --config roles=broker,controller
juju deploy redis-k8s --channel latest/edge

juju integrate sentry-relay-k8s kafka-k8s
juju integrate sentry-relay-k8s redis-k8s
juju integrate sentry-relay-k8s sentry-k8s
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `log-level` | `info` | Relay's log level (`trace`, `debug`, `info`, `warn`, `error`). |

## Integrations

- **`kafka`** (`kafka_client`), **`redis`** (`redis`) — required backends for
  the processing pipeline.
- **`sentry`** (`sentry_relay`, requires) — the Sentry charm hands Relay its web
  (upstream) URL.
- **`ingress`** (`ingress`, requires, optional) — expose Relay's intake port
  through Traefik.
- **`metrics-endpoint`**, **`grafana-dashboard`** (provides), **`logging`**
  (requires) — the Canonical Observability Stack.

When integrated with `kafka-k8s` (which authenticates clients with SASL/SCRAM),
the charm adds the SASL credentials to Relay's `processing.kafka_config`.

## Security

See the repository [`SECURITY.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/SECURITY.md).

## Contributing

See [`CONTRIBUTING.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/CONTRIBUTING.md).
Licensed under [Apache-2.0](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/LICENSE).
