# Sentry Operators

A set of [Juju](https://juju.is) charms that deploy and operate
[self-hosted, open-source Sentry](https://develop.sentry.dev/self-hosted/) —
the error-tracking and performance-monitoring platform — on Kubernetes.

> [!WARNING]
> This project is under active development. It is **not** affiliated with or
> endorsed by Functional Software, Inc. (Sentry). "Sentry" is a trademark of
> its respective owner; it is used here only to describe the software these
> charms deploy.

## What's here

Self-hosted Sentry is not a single service: it is a fleet of cooperating
workloads (a Django web app, Celery workers, a Relay ingestion proxy, the
Snuba/ClickHouse analytics tier, Kafka, and several stateful backends). Rather
than cram all of that into one opaque pod, this repository follows *the Juju
way*: each cohesive workload is its own charm, and the charms are wired
together — and to Canonical's data and observability charms — with Juju
integrations.

| Charm | Directory | Responsibility |
|-------|-----------|----------------|
| `sentry-k8s` | [`charms/sentry-k8s`](charms/sentry-k8s) | Sentry web UI, API, Celery workers, cron/beat, ingest & post-process consumers |
| `sentry-relay-k8s` | [`charms/sentry-relay-k8s`](charms/sentry-relay-k8s) | The Relay event-ingestion proxy |
| `sentry-snuba-k8s` | [`charms/sentry-snuba-k8s`](charms/sentry-snuba-k8s) | Snuba API + consumers, the search/analytics service over ClickHouse |
| `clickhouse-k8s` | [`charms/clickhouse-k8s`](charms/clickhouse-k8s) | ClickHouse column store used by Snuba |

The rocks (OCI images) that back these charms are built with
[Rockcraft](https://canonical-rockcraft.readthedocs-hosted.com/) and live in
[`rocks/`](rocks).

### Integrations

The charms relate to Canonical's maintained data charms instead of bundling
their own copies:

- [`postgresql-k8s`](https://charmhub.io/postgresql-k8s) — primary database
- [`redis-k8s`](https://charmhub.io/redis-k8s) — cache, buffers, queues, rate limiting
- [`kafka-k8s`](https://charmhub.io/kafka-k8s) — the event/stream bus between Relay, Sentry and Snuba

…and to the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack)
(`cos-lite`) for metrics, logs, dashboards and tracing, plus
[`traefik-k8s`](https://charmhub.io/traefik-k8s) for ingress.

## Quick start

See [`docs/`](docs) for the full tutorial. In short:

```bash
juju add-model sentry
# data backends
juju deploy postgresql-k8s --channel 14/stable --trust
juju deploy redis-k8s --channel latest/edge
juju deploy kafka-k8s --channel 3/stable --config roles=broker,controller
# sentry
juju deploy ./clickhouse-k8s_*.charm --resource ...
juju deploy ./sentry-snuba-k8s_*.charm --resource ...
juju deploy ./sentry-relay-k8s_*.charm --resource ...
juju deploy ./sentry-k8s_*.charm --resource ...
# wire it together (see the bundle in releases/)
```

A ready-made [bundle / Terraform module](releases) wires the whole topology
together in one step.

## Development

This is a `charmcraft`/`rockcraft` monorepo. Each charm and rock is
independently buildable:

```bash
cd charms/sentry-k8s && charmcraft pack
cd rocks/sentry && rockcraft pack
```

Run the full check suite with `tox` from any charm directory (`tox -e lint`,
`tox -e unit`, `tox -e integration`).

## License

Apache-2.0 — see [LICENSE](LICENSE). The Sentry software these charms deploy is
licensed separately by its authors (see the
[Functional Source License / BSL terms](https://github.com/getsentry/self-hosted)).
