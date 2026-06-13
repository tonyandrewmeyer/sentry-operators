# sentry-k8s

A [Juju](https://juju.is) charm that runs the application tier of self-hosted,
open-source [Sentry](https://develop.sentry.dev/self-hosted/) on Kubernetes:
the web UI/API, the task scheduler and workers, and the ingest, post-process and
subscription consumers.

This is the centrepiece of the
[`sentry-operators`](https://github.com/tonyandrewmeyer/sentry-operators) charm
set. It also runs the **taskbroker** and **symbolicator** services as sidecar
containers in the same pod.

## Usage

Sentry needs PostgreSQL, Redis, Kafka and the Snuba analytics tier. The Snuba
tier (`sentry-snuba-k8s` + `clickhouse-k8s`) is in this repository; the data
backends are Canonical charms:

```bash
juju deploy postgresql-k8s --channel 14/stable --trust \
  --config plugin_citext_enable=true --config plugin_pg_trgm_enable=true
juju deploy kafka-k8s --channel 3/stable --config roles=broker,controller \
  --config message-max-bytes=52428800 --trust
juju deploy redis-k8s --channel latest/edge --trust

juju deploy clickhouse-k8s --channel latest/edge --trust
juju deploy sentry-snuba-k8s --channel latest/edge --trust
juju integrate sentry-snuba-k8s clickhouse-k8s
juju integrate sentry-snuba-k8s kafka-k8s
juju integrate sentry-snuba-k8s redis-k8s

juju deploy sentry-k8s --channel latest/edge --trust
juju integrate sentry-k8s postgresql-k8s
juju integrate sentry-k8s kafka-k8s
juju integrate sentry-k8s redis-k8s
juju integrate sentry-k8s sentry-snuba-k8s

# Event intake and the UI ingress
juju deploy sentry-relay-k8s --channel latest/edge --trust
juju integrate sentry-relay-k8s kafka-k8s
juju integrate sentry-relay-k8s redis-k8s
juju integrate sentry-relay-k8s sentry-k8s
juju deploy traefik-k8s --channel latest/stable --trust
juju integrate traefik-k8s sentry-k8s
juju integrate traefik-k8s sentry-relay-k8s
```

Create the first admin user:

```bash
juju run sentry-k8s/leader create-admin email=you@example.com
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `feature-complete` | `true` | Run transactions/metrics/profiling/replays/crons consumers as well as error tracking. |
| `event-retention-days` | `90` | Event retention. |
| `taskworker-concurrency` | `4` | Task worker concurrency. |
| `enable-symbolicator` | `true` | Run symbolicator for stack-trace symbolication. |
| `smtp-*`, `mail-from` | — | Optional outbound email. |

## Actions

- **`create-admin`** `email=<addr> [password=<pw>]` — create a superuser; the
  password is stored in a Juju secret whose id is returned.

## Integrations

`database` (postgresql_client), `kafka` (kafka_client), `redis` (redis), `snuba`
(sentry_snuba) — required. `sentry-relay` (sentry_relay, provides), `ingress`,
`metrics-endpoint`, `grafana-dashboard`, `logging` — optional.

## Security

The generated `system.secret-key` and admin passwords are stored in Juju
secrets. See the repository
[`SECURITY.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/SECURITY.md).

## Contributing

See [`CONTRIBUTING.md`](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/CONTRIBUTING.md).
Licensed under [Apache-2.0](https://github.com/tonyandrewmeyer/sentry-operators/blob/main/LICENSE).
