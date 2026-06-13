# Releases

This directory contains ready-made ways to deploy the whole self-hosted Sentry
topology in one step:

- [`bundle.yaml`](bundle.yaml) — a Juju bundle that deploys all four
  `sentry-operators` charms plus PostgreSQL, Redis, Kafka and Traefik, with
  every integration wired.
- The repository's root [`terraform/`](../terraform) module is the equivalent
  for Terraform users — it composes the four per-charm modules and the data
  charms.

## Prerequisites

- A Kubernetes cluster with a bootstrapped Juju controller (`juju >= 3.6`).
- Plenty of room: a **feature-complete** deployment is resource hungry; budget
  around **16 GB of RAM**. For a lighter, errors-only stack set
  `feature-complete=false` on `sentry-k8s` and `sentry-snuba-k8s` (see below).

## Deploy

```bash
juju add-model sentry
juju deploy ./releases/bundle.yaml --trust
```

`--trust` is required: several applications (the Sentry charms and the data
charms) need permission to manage Kubernetes resources on your behalf.

Watch it settle:

```bash
juju status --watch 5s
```

The bundle pins the upstream OCI images (Sentry/Snuba/Relay `26.5.2`, the
Altinity ClickHouse build) as resources, so it deploys the exact versions the
charms are validated against.

## Lighter, errors-only deployment

To drop the feature-complete consumers (transactions, metrics, profiling,
replays, crons, uptime, feedback) and run a smaller footprint, override the two
`feature-complete` options at deploy time, or after deploy:

```bash
juju config sentry-k8s feature-complete=false
juju config sentry-snuba-k8s feature-complete=false
```

Keep the two values in step so the consumer set and ClickHouse TTLs line up.

## After deploy

Create the first admin user and reach the UI — see the
[tutorial](../docs/tutorial.md) for the full walkthrough, including how to read
the admin password out of the returned Juju secret and how to find the Traefik
ingress URL.

```bash
juju run sentry-k8s/leader create-admin email=admin@example.com
juju run traefik-k8s/0 show-proxied-endpoints
```
