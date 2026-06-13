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
workloads (a Django web app, async task workers, a Relay ingestion proxy, the
Snuba/ClickHouse analytics tier, Kafka, and several stateful backends). Rather
than cram all of that into one opaque pod, this repository follows *the Juju
way*: each cohesive workload is its own charm, and the charms are wired
together — and to Canonical's data and observability charms — with Juju
integrations.

| Charm | Directory | Responsibility |
|-------|-----------|----------------|
| `sentry-k8s` | [`charms/sentry-k8s`](charms/sentry-k8s) | Sentry web UI & API, the task worker/scheduler and the taskbroker, the ingest and post-process consumers, and (optionally) the symbolicator |
| `sentry-relay-k8s` | [`charms/sentry-relay-k8s`](charms/sentry-relay-k8s) | The Relay event-ingestion proxy — the front door for incoming events |
| `sentry-snuba-k8s` | [`charms/sentry-snuba-k8s`](charms/sentry-snuba-k8s) | Snuba API + consumers, the search/analytics service over ClickHouse |
| `clickhouse-k8s` | [`charms/clickhouse-k8s`](charms/clickhouse-k8s) | The ClickHouse column store that Snuba reads and writes |

Sentry 26.5.2 has moved off Celery; the worker tier is `taskworker` /
`taskworker-scheduler` backed by the separate **taskbroker** service, all run as
Pebble services inside `sentry-k8s`.

The workloads run upstream's own published, pinned OCI images
(`ghcr.io/getsentry/{sentry,relay,snuba,taskbroker,symbolicator}:26.5.2` and
`altinity/clickhouse-server`) attached as charm resources — Sentry's images are
large multi-stage builds and are the upstream-supported artifact, so the charms
consume them directly rather than rebuilding them. The [`rocks/`](rocks)
directory is reserved for any auxiliary images we might build with
[Rockcraft](https://canonical-rockcraft.readthedocs-hosted.com/); it is
currently empty.

### Integrations

The charms relate to Canonical's maintained data charms instead of bundling
their own copies:

- [`postgresql-k8s`](https://charmhub.io/postgresql-k8s) — primary database
- [`redis-k8s`](https://charmhub.io/redis-k8s) — cache, buffers, rate limiting
- [`kafka-k8s`](https://charmhub.io/kafka-k8s) — the event/stream bus between Relay, Sentry and Snuba

…and to the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack)
(`cos-lite`) for metrics, logs, dashboards and tracing, plus
[`traefik-k8s`](https://charmhub.io/traefik-k8s) for ingress.

## Quick start

The full walkthrough is in [`docs/tutorial.md`](docs/tutorial.md). In outline:
deploy the data backends (`postgresql-k8s`, `redis-k8s`, `kafka-k8s`), then the
four charms with their image resources, integrate them, and create the first
admin user:

```bash
# build the charms (until they are published to Charmhub)
for c in clickhouse-k8s sentry-snuba-k8s sentry-relay-k8s sentry-k8s; do
  (cd charms/$c && charmcraft pack)
done

# deploy + integrate (see docs/tutorial.md for the resource/config flags)
# ...then create the first admin user:
juju run sentry-k8s/0 create-admin email=you@example.com
```

A Juju [bundle](releases/bundle.yaml) ([`releases/`](releases)) and an
all-in-one [Terraform module](terraform) ([`terraform/`](terraform)) wire the
whole topology — charms, backends and integrations — together in one step;
both deploy the charms from Charmhub, so they apply once the charms are
published.

Once everything is `active`, point a Sentry SDK at the project DSN (served via
Relay) and your events show up as issues — see the end-to-end demo below.

## Demo

[`demos/end-to-end.md`](demos/end-to-end.md) sends a real error through the
Relay charm and follows it across the pipeline — Kafka → the Sentry consumers →
a Postgres issue and Snuba → ClickHouse — finishing with screenshots of the
issue in the live Sentry UI. It is an executable
[showboat](https://pypi.org/project/showboat/) document, so it is also
reproducible proof.

## Development

This is a `charmcraft` monorepo; each charm is independently buildable:

```bash
cd charms/sentry-k8s && charmcraft pack
```

Run the checks with `tox` from any charm directory (`tox -e lint`,
`tox -e static`, `tox -e unit`, `tox -e integration`). Install the
[pre-commit](https://pre-commit.com/) hooks to run formatting, linting and unit
tests automatically before every commit:

```bash
uv tool install pre-commit   # or: pip install pre-commit
pre-commit install
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for more.

## License

Apache-2.0 — see [LICENSE](LICENSE). The Sentry software these charms deploy is
licensed separately by its authors (see the
[Functional Source License / BSL terms](https://github.com/getsentry/self-hosted)).
