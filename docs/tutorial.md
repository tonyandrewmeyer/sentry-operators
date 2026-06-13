# Tutorial: deploy self-hosted Sentry from scratch

By the end of this tutorial you will have a working self-hosted Sentry running
on Kubernetes, an admin account, and a project receiving a test event — all
deployed and wired together with Juju.

## What you will build

The four `sentry-operators` charms (`sentry-k8s`, `sentry-relay-k8s`,
`sentry-snuba-k8s`, `clickhouse-k8s`) related to PostgreSQL, Redis and Kafka,
fronted by Traefik ingress.

## Prerequisites

- A Kubernetes cluster with a bootstrapped Juju controller, `juju >= 3.6`
  (MicroK8s with the `hostpath-storage`, `dns` and `metallb` add-ons is fine).
- `juju` on your `PATH`.
- **Memory.** A feature-complete deployment is resource hungry — budget around
  **16 GB of RAM**. For a lighter, errors-only stack set
  `feature-complete=false` on `sentry-k8s` and `sentry-snuba-k8s` (covered at
  the end).

This tutorial deploys the four charms from a local channel (`latest/edge`); to
deploy from locally packed `.charm` files instead, swap the
`--channel latest/edge` flags for `./<charm>_*.charm` paths.

## 1. Create a model

```bash
juju add-model sentry
```

## 2. Deploy the data backends

PostgreSQL holds Sentry's metadata. Sentry needs the `citext` and `pg_trgm`
extensions, so enable them at deploy time:

```bash
juju deploy postgresql-k8s --channel 14/stable --trust \
  --config plugin_citext_enable=true \
  --config plugin_pg_trgm_enable=true
```

Redis is the cache, buffers, quotas and queues:

```bash
juju deploy redis-k8s --channel latest/edge
```

Kafka is the event spine. Deploy it in combined broker+controller (KRaft) mode:

```bash
juju deploy kafka-k8s --channel 3/stable --trust \
  --config roles=broker,controller
```

## 3. Deploy the Sentry charms

```bash
juju deploy clickhouse-k8s   --channel latest/edge --trust
juju deploy sentry-snuba-k8s --channel latest/edge --trust
juju deploy sentry-relay-k8s --channel latest/edge --trust
juju deploy sentry-k8s       --channel latest/edge --trust
```

`--trust` lets these charms manage their Kubernetes resources.

## 4. Wire the integrations

The charms do nothing until they are related. Snuba needs ClickHouse, Kafka and
Redis:

```bash
juju integrate sentry-snuba-k8s:clickhouse clickhouse-k8s:clickhouse
juju integrate sentry-snuba-k8s:kafka kafka-k8s:kafka-client
juju integrate sentry-snuba-k8s:redis redis-k8s:redis
```

Sentry needs PostgreSQL, Kafka, Redis and Snuba:

```bash
juju integrate sentry-k8s:database postgresql-k8s:database
juju integrate sentry-k8s:kafka kafka-k8s:kafka-client
juju integrate sentry-k8s:redis redis-k8s:redis
juju integrate sentry-k8s:snuba sentry-snuba-k8s:snuba
```

Relay needs Kafka, Redis and the Sentry upstream:

```bash
juju integrate sentry-relay-k8s:kafka kafka-k8s:kafka-client
juju integrate sentry-relay-k8s:redis redis-k8s:redis
juju integrate sentry-relay-k8s:sentry sentry-k8s:sentry-relay
```

Once related, the leader units run the one-off migrations (`snuba bootstrap`,
`sentry upgrade`) before the workloads start serving. Watch progress:

```bash
juju status --watch 5s
```

Wait until every application is `active`/`idle`.

## 5. Add ingress

Deploy Traefik and route both the Sentry UI and the Relay intake endpoint
through it:

```bash
juju deploy traefik-k8s --channel latest/stable --trust
juju integrate sentry-k8s:ingress traefik-k8s:ingress
juju integrate sentry-relay-k8s:ingress traefik-k8s:ingress
```

## 6. Create an admin user

The `create-admin` action creates a Sentry superuser. If you omit `password`, a
random one is generated and stored in a Juju secret:

```bash
juju run sentry-k8s/leader create-admin email=admin@example.com
```

The action returns a `secret-id`. Reveal the generated password with:

```bash
juju show-secret --reveal <secret-id>
```

(You can also pass your own password:
`juju run sentry-k8s/leader create-admin email=admin@example.com password=...`.)

## 7. Reach the UI

Ask Traefik for the proxied endpoints:

```bash
juju run traefik-k8s/0 show-proxied-endpoints
```

Open the `sentry-k8s` URL from the output in your browser and log in with the
admin email and the password you revealed in step 6.

## 8. Create a project and send a test event

1. In the Sentry UI, create a new **project** (pick a platform, e.g. Python).
2. Sentry shows you a **DSN** — a URL of the form
   `https://<public-key>@<your-relay-host>/<project-id>`. Note that the host is
   your Relay ingress endpoint, not sentry.io.
3. Send a test event. For Python:

   ```bash
   pip install sentry-sdk
   ```

   ```python
   import sentry_sdk

   sentry_sdk.init(dsn="https://<public-key>@<your-relay-host>/<project-id>")

   try:
       1 / 0
   except ZeroDivisionError:
       sentry_sdk.capture_exception()
   ```

The event flows Relay → Kafka → Sentry consumers → Snuba → ClickHouse, and
appears in your project's **Issues** view within a few seconds.

## A lighter, errors-only deployment

The full feature set (transactions, metrics, profiling, replays, crons, uptime,
feedback) is what drives the ~16 GB recommendation. For a smaller footprint that
only does error tracking, turn off `feature-complete` on the two charms that
have it — either at deploy time
(`juju deploy ... --config feature-complete=false`) or afterwards:

```bash
juju config sentry-k8s feature-complete=false
juju config sentry-snuba-k8s feature-complete=false
```

Keep the two values in step so the consumer set and the ClickHouse retention
TTLs line up.

## Next steps

- [Set up observability](how-to-observability.md)
- [Upgrade and operate (day 2)](how-to-upgrade.md)
- [Reference: configuration, integrations and actions](reference-configuration.md)
- [Security hardening](security.md)
