# How to set up observability

All four `sentry-operators` charms speak the
[Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack)
(COS) relation interfaces, so you can ship their metrics, logs and dashboards to
`cos-lite` (Prometheus, Loki, Grafana, and Tempo for tracing) with a handful of
integrations.

## The relevant endpoints

Each charm exposes these observability endpoints:

| Endpoint | Interface | Direction | Charms |
|----------|-----------|-----------|--------|
| `metrics-endpoint` | `prometheus_scrape` | provides | all four |
| `grafana-dashboard` | `grafana_dashboard` | provides | all four |
| `logging` | `loki_push_api` | requires | all four |

So Prometheus scrapes the charm's `metrics-endpoint`, the charm pushes logs to
Loki's `logging` endpoint, and the charm provides dashboards to Grafana.

## Option A: COS in the same model

Deploy `cos-lite` and relate each charm directly.

```bash
juju deploy cos-lite --trust
```

Then, for **each** of the four charms, wire up metrics, logs and dashboards.
For example for `sentry-k8s`:

```bash
juju integrate sentry-k8s:metrics-endpoint prometheus:metrics-endpoint
juju integrate sentry-k8s:logging loki:logging
juju integrate sentry-k8s:grafana-dashboard grafana:grafana-dashboard
```

Repeat for `sentry-snuba-k8s`, `sentry-relay-k8s` and `clickhouse-k8s`:

```bash
for app in sentry-snuba-k8s sentry-relay-k8s clickhouse-k8s; do
  juju integrate "$app:metrics-endpoint" prometheus:metrics-endpoint
  juju integrate "$app:logging" loki:logging
  juju integrate "$app:grafana-dashboard" grafana:grafana-dashboard
done
```

> The application names `prometheus`, `loki` and `grafana` are the ones the
> `cos-lite` bundle deploys.

Get the Grafana URL and admin password:

```bash
juju run grafana/leader get-admin-password
juju run traefik/0 show-proxied-endpoints   # cos-lite's own traefik
```

## Option B: COS in a separate model (recommended)

In production, run COS in its own model (often its own cloud) and consume it
across a model boundary with Juju **offers**.

In the COS model:

```bash
juju switch cos
juju deploy cos-lite --trust
juju offer prometheus:receive-remote-write
juju offer loki:logging
juju offer grafana:grafana-dashboard
```

Back in the `sentry` model, consume the offers and relate. Because Prometheus
scraping does not cross models, use the **Grafana Agent** as the cross-model
forwarder for metrics; logs and dashboards relate to the offers directly:

```bash
juju switch sentry
juju deploy grafana-agent-k8s grafana-agent --channel latest/stable

# Each charm sends its metrics/logs/dashboards into the agent...
for app in sentry-k8s sentry-snuba-k8s sentry-relay-k8s clickhouse-k8s; do
  juju integrate "$app:metrics-endpoint" grafana-agent:metrics-endpoint
  juju integrate "$app:logging" grafana-agent:logging-provider
  juju integrate "$app:grafana-dashboard" grafana-agent:grafana-dashboards-consumer
done

# ...and the agent forwards everything to the COS offers.
juju integrate grafana-agent cos.prometheus
juju integrate grafana-agent cos.loki
juju integrate grafana-agent cos.grafana
```

(`cos.prometheus`, `cos.loki` and `cos.grafana` are the consumed offer URLs;
substitute the exact URLs `juju offer` printed, e.g.
`admin/cos.loki`.)

## What you get

- **Metrics** in Prometheus from every charm's workload (`metrics-endpoint`).
- **Logs** in Loki, with the per-charm Pebble service logs (`logging`).
- **Dashboards** auto-provisioned in Grafana (`grafana-dashboard`).

## Tracing (optional)

The Sentry-family charms can emit their own charm/workload traces to Tempo,
which `cos-lite` includes. Relate the relevant `tracing` endpoint to Tempo's
coordinator if your COS deployment exposes it; see the
[design notes](design.md) for the tracing interface used.
