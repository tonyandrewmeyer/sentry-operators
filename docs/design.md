# Design: self-hosted Sentry on Juju/Kubernetes

This document records the architecture of the `sentry-operators` charm set and
the decisions behind it. It is the reference for contributors and reviewers.

## Goal

Deploy and operate **self-hosted, open-source Sentry 26.5.x** on Kubernetes the
Juju way: cohesive workloads as separate charms, stateful backends provided by
Canonical's maintained data charms, and first-class Day-2 operations
(migrations, scaling, backups, upgrades) and observability.

## Upstream reality (what we are modelling)

Modern self-hosted Sentry (26.5.2) is a fleet of ~40 containers. The important
structural facts:

- **One application image** (`ghcr.io/getsentry/sentry`) runs *many* processes
  selected by command: `run web`, `run taskworker`, `run taskworker-scheduler`,
  and ~25 `run consumer <name>` ingest/forwarder/subscription consumers.
- Sentry **no longer uses Celery**; async work flows through **taskbroker** (a
  separate Rust service, gRPC :50051, backed by SQLite) which `taskworker`
  processes pull from.
- **Snuba** (`ghcr.io/getsentry/snuba`) is the analytics service over
  **ClickHouse**: a uWSGI API (:1218) plus many `rust-consumer` /
  `subscriptions-scheduler-executor` processes.
- **Relay** (`ghcr.io/getsentry/relay`) is the event-intake proxy that writes to
  Kafka.
- **Kafka is the spine**; **Postgres** holds metadata; **Redis** holds
  buffers/quotas/TSDB/digests/cache; **ClickHouse** holds the event analytics.
- Sentry's config (`sentry.conf.py`) is **plain Python that reads environment
  variables** — so a charm can fully control connection settings by pushing its
  own config file and env into the container.

## Charm topology

Cohesion boundary = "shares an image, config and lifecycle". That yields four
charms:

```
                         ┌─────────────────┐
   ingress (traefik) ───►│ sentry-relay-k8s│  Relay: event intake → Kafka
                         └────────┬────────┘
                                  │ sentry-relay (web upstream + secret-key)
                         ┌────────▼────────┐
   ingress (traefik) ───►│   sentry-k8s    │  web + taskworker + scheduler +
                         │  (+ taskbroker,  │  ~25 consumers, taskbroker,
                         │   symbolicator)  │  symbolicator (sidecar containers)
                         └──┬───┬───┬───┬───┘
            postgresql_client│   │   │   │ sentry-snuba (Snuba HTTP API)
              redis ─────────┘   │   │   └────────────┐
              kafka_client ──────┘   │                │
                                     │        ┌───────▼────────┐
                                     │        │ sentry-snuba-k8s│ Snuba API+consumers
                                     │        └───┬────────┬────┘
                                     │   kafka────┘        │ clickhouse
                                     │   redis             │
                                     │              ┌──────▼───────┐
                                     │              │ clickhouse-k8s│ ClickHouse store
                                     │              └──────────────┘
   Data charms (related, not bundled): postgresql-k8s, redis-k8s, kafka-k8s
   Observability (related): cos-lite (prometheus, loki, grafana, tempo)
```

| Charm | Containers (images) | Pebble services |
|-------|---------------------|-----------------|
| `clickhouse-k8s` | clickhouse (altinity) | `clickhouse-server` |
| `sentry-snuba-k8s` | snuba | `snuba-api` + per-storage `rust-consumer`s + subscription executors |
| `sentry-relay-k8s` | relay | `relay` |
| `sentry-k8s` | sentry; taskbroker; symbolicator | `web`, `taskworker`, `taskscheduler`, `events-consumer`, `attachments-consumer`, `post-process-forwarder-errors`, `subscription-consumer-events`, … (+ feature-complete consumers); `taskbroker`; `symbolicator`, `symbolicator-cleanup` |

Why not one charm? A single charm would bury ~40 processes and three images in
one opaque unit, defeating independent scaling, health and observability. Why
not ~40 charms (one per consumer)? The processes share an image, config and
release lifecycle; the natural Juju unit is the *application*, with optional
consumer processes toggled by config. Pebble runs the many same-image processes
as services inside one container; genuinely distinct images (taskbroker,
symbolicator) are sidecar containers in the same pod.

## Integrations (relations)

Requirer/provider interfaces used (Canonical charm libraries):

| Purpose | Interface | Provider charm | Library |
|---------|-----------|----------------|---------|
| Postgres | `postgresql_client` | postgresql-k8s | `data_platform_libs.v0.data_interfaces` |
| Redis | `redis` | redis-k8s | `redis_k8s.v0.redis` |
| Kafka | `kafka_client` | kafka-k8s | `data_platform_libs.v0.data_interfaces` |
| ClickHouse | `sentry_clickhouse` (this repo) | clickhouse-k8s | local lib |
| Snuba | `sentry_snuba` (this repo) | sentry-snuba-k8s | local lib |
| Relay↔Sentry | `sentry_relay` (this repo) | sentry-k8s | local lib |
| Ingress | `ingress` | traefik-k8s | `traefik_k8s.v2.ingress` |
| Metrics | `prometheus_scrape` | prometheus-k8s | `prometheus_k8s.v0.prometheus_scrape` |
| Logs | `loki_push_api` | loki-k8s | `loki_k8s.v1.loki_push_api` |
| Dashboards | `grafana_dashboard` | grafana-k8s | `grafana_k8s.v0.grafana_dashboard` |
| Tracing | `tracing` | tempo (cos) | `tempo_coordinator_k8s.v0.charm_tracing` |

## Decisions to reduce footprint without forking Sentry

To keep the stack deployable (and within constrained RAM) while staying faithful:

1. **Drop memcached** — use Django 4's built-in `RedisCache` for the default
   cache (Sentry already uses Redis for its primary cache). One less backend.
2. **Drop pgbouncer** — connect Sentry directly to Postgres. Migrations require
   a direct connection regardless, and a single org install does not need
   transaction pooling. (A `pgbouncer-k8s` relation can be added later.)
3. **nodestore → Postgres (django backend)** instead of S3, and **filestore →
   filesystem** on a Juju storage volume. Because web/workers/consumers are
   Pebble services in *one* container, the filesystem is shared without needing
   ReadWriteMany. This removes SeaweedFS from the core path.
4. **SMTP optional** via config (point at an external relay) rather than
   bundling Exim.
5. **Profiling/replays/S3 profiles** are *feature-complete* extras, enabled by
   config and (for profile storage) an optional S3 relation.

These keep the **errors-only** path to: `postgresql-k8s + redis-k8s + kafka-k8s`
(related) and `clickhouse-k8s + sentry-snuba-k8s + sentry-relay-k8s + sentry-k8s`
(this repo). `feature-complete` turns on the remaining consumers and optional
backends.

## Images / rocks

The Sentry-family images are large, multi-stage builds (Python 3.13 + Rust +
JS asset pipeline) that are the *supported upstream artifacts*. The charms
consume them pinned by tag **and digest** as OCI resources rather than forking
that build. Rockcraft is used for the auxiliary/glue images we genuinely own.
This is documented per charm in `rockcraft.yaml` / the resource metadata, and
revisited as the listing review requires.

## Day-2 operations

- **Migrations** (`snuba bootstrap`, `sentry upgrade`) run once via the leader
  unit, gated so workloads do not serve before schemas exist; re-run on
  `upgrade-charm` after an image bump.
- **Admin user** creation via a `create-admin` action (writes credentials to a
  Juju secret).
- **secret-key** generated once and stored in a Juju (peer) secret; surfaced to
  Relay over the relation for registration.
- **Retention** (`SENTRY_EVENT_RETENTION_DAYS`) is a config option; a periodic
  `sentry cleanup` runs via a Pebble check/timer.
- **Scaling**: `juju scale-application` on web/consumer charms; consumer toggles
  via config.
