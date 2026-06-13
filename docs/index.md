# sentry-operators

A set of [Juju](https://juju.is) charms that deploy and operate
[self-hosted, open-source Sentry](https://develop.sentry.dev/self-hosted/) — the
error-tracking and performance-monitoring platform — on Kubernetes, the Juju
way.

> **Note**
> This project is not affiliated with or endorsed by Functional Software, Inc.
> (Sentry). "Sentry" is a trademark of its respective owner.

Self-hosted Sentry is not a single service: it is a fleet of cooperating
workloads. Rather than cram all of that into one opaque pod, this charm set
splits it into four cohesive charms and relates them to Canonical's maintained
data and observability charms.

## The four charms

| Charm | Responsibility |
|-------|----------------|
| [`sentry-k8s`](https://charmhub.io/sentry-k8s) | Sentry web UI and API, the task scheduler and task workers, the taskbroker and symbolicator sidecars, and the fleet of Kafka ingest / post-process consumers. Runs migrations, owns the system secret key, and creates the first admin user. |
| [`sentry-relay-k8s`](https://charmhub.io/sentry-relay-k8s) | Relay, the event-intake proxy: it authenticates against the Sentry upstream, normalises and rate-limits incoming events, and forwards them onto Kafka. |
| [`sentry-snuba-k8s`](https://charmhub.io/sentry-snuba-k8s) | Snuba, the search and analytics service: its HTTP query API plus the consumers and subscription executors that stream events into ClickHouse. |
| [`clickhouse-k8s`](https://charmhub.io/clickhouse-k8s) | A single-node ClickHouse column store tuned for Snuba. |

These relate to Canonical's data charms —
[`postgresql-k8s`](https://charmhub.io/postgresql-k8s) (metadata),
[`redis-k8s`](https://charmhub.io/redis-k8s) (cache/buffers/queues) and
[`kafka-k8s`](https://charmhub.io/kafka-k8s) (the event spine) — instead of
bundling their own copies, to [`traefik-k8s`](https://charmhub.io/traefik-k8s)
for ingress, and to the
[Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack)
for metrics, logs, dashboards and tracing.

## Architecture

```
                         ┌──────────────────┐
   ingress (traefik) ───►│ sentry-relay-k8s │  Relay: event intake → Kafka
                         └────────┬─────────┘
                                  │ sentry-relay (web upstream + secret-key)
                         ┌────────▼─────────┐
   ingress (traefik) ───►│    sentry-k8s    │  web + taskworker + scheduler +
                         │ (+ taskbroker,   │  ~25 consumers, taskbroker,
                         │   symbolicator)  │  symbolicator (sidecar containers)
                         └──┬───┬───┬───┬───┘
            database (pg)───┘   │   │   │ snuba (Snuba HTTP API)
            redis ─────────────┘   │   └───────────────┐
            kafka ────────────────┘                    │
                                              ┌─────────▼────────┐
                                              │ sentry-snuba-k8s │  Snuba API + consumers
                                              └───┬──────────┬───┘
                                       kafka ─────┘          │ clickhouse
                                       redis                 │
                                                    ┌────────▼───────┐
                                                    │ clickhouse-k8s │  ClickHouse store
                                                    └────────────────┘

   Data charms (related, not bundled): postgresql-k8s, redis-k8s, kafka-k8s
   Observability (related): cos-lite (prometheus, loki, grafana, tempo)
```

For the full rationale — why four charms, how the ~40 upstream processes map to
Pebble services, and which backends were dropped to keep the footprint
manageable — see [`design.md`](design.md).

## Documentation

This documentation follows the [Diátaxis](https://diataxis.fr/) framework.

- **[Tutorial](tutorial.md)** — deploy a complete self-hosted Sentry from
  scratch, create an admin user, and send a test event.
- **How-to guides**
  - [Set up observability](how-to-observability.md) — relate the charms to
    `cos-lite` for metrics, logs and dashboards.
  - [Upgrade and operate (day 2)](how-to-upgrade.md) — refresh charms, run
    backups, scale, and rotate the secret key.
- **[Reference](reference-configuration.md)** — every config option, every
  integration endpoint, and the actions, for all four charms.
- **[Security](security.md)** — hardening guidance: TLS, network isolation,
  secret handling and Kafka authentication.
- **[Design](design.md)** — the architecture and the decisions behind it.
