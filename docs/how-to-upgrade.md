# How to upgrade and operate (day 2)

This guide covers ongoing operation of a deployed Sentry stack: upgrading the
charms, understanding how migrations re-run, taking backups, scaling, and
rotating the system secret key.

## Upgrading the charms

Each charm is upgraded independently with `juju refresh`. To move a charm to a
newer revision on its channel:

```bash
juju refresh sentry-k8s
juju refresh sentry-snuba-k8s
juju refresh sentry-relay-k8s
juju refresh clickhouse-k8s
```

To switch channels (e.g. from edge to stable) or pin a revision:

```bash
juju refresh sentry-k8s --channel latest/stable
juju refresh sentry-k8s --revision 42
```

> **Order matters.** When an upgrade bumps the underlying image version, refresh
> the storage/analytics tiers (`clickhouse-k8s`, `sentry-snuba-k8s`) and the
> application (`sentry-k8s`) before `sentry-relay-k8s`, and keep the
> Sentry/Snuba/Relay image versions in step — they are released together (the
> charms pin matching `26.5.x` tags).

### How migrations re-run

The leader unit runs the one-off schema work — `snuba bootstrap` /
`snuba migrations migrate` for Snuba, and `sentry upgrade` for Sentry — gated so
the workloads do not serve until the schema exists. On `juju refresh`, the
`upgrade-charm` hook re-runs these migrations when the pinned image has changed,
so a charm upgrade that carries a new Sentry/Snuba release applies the new
migrations automatically. Watch `juju status` until the application returns to
`active`/`idle`; the unit message indicates when migrations are running.

## Backups

There is no single "Sentry backup": back up the **state** backends. The
analytics tier is re-derivable.

- **PostgreSQL (metadata — the source of truth).** Use the `postgresql-k8s`
  charm's backup support. Configure an S3 relation and run the charm's
  `create-backup` action, or take a logical dump:

  ```bash
  # via the charm's built-in backups (preferred)
  juju integrate postgresql-k8s s3-integrator
  juju run postgresql-k8s/leader create-backup

  # or an ad-hoc logical dump
  juju ssh --container postgresql postgresql-k8s/leader \
    'pg_dump -U operator sentry' > sentry-pg.sql
  ```

- **ClickHouse (event analytics).** ClickHouse is **re-derivable from Kafka**:
  the events live on the Kafka log and Snuba's consumers replay them into
  ClickHouse. For most installs you do not need to back ClickHouse up; protect
  Kafka's retention instead. If you want point-in-time event recovery, snapshot
  the `clickhouse-k8s` `data` storage volume.

- **Juju secrets.** The generated `system.secret-key`, Relay credentials and
  admin passwords live in Juju secrets and are part of the controller's state;
  ensure your controller is backed up (`juju create-backup` on the controller
  model).

## Scaling

Scale the stateless/horizontally-scalable tiers with `juju scale-application`:

```bash
juju scale-application sentry-relay-k8s 3      # more event intake
juju scale-application sentry-k8s 2            # more web/consumers
juju scale-application sentry-snuba-k8s 2      # more analytics consumers
```

> Scale `clickhouse-k8s` with care — this charm runs a **single-node**
> ClickHouse tuned for Snuba; it is not a multi-node cluster. PostgreSQL and
> Kafka scale via their own charms' guidance.

You can also trade footprint for features without changing scale by toggling the
consumer set:

```bash
juju config sentry-k8s feature-complete=false
juju config sentry-snuba-k8s feature-complete=false
```

## Rotating the system secret key

Sentry's `system.secret-key` is generated once and held in a Juju (peer) secret;
it is surfaced to Relay over the `sentry-relay` relation. Rotate it through Juju
so both ends pick up the new value:

```bash
# list the application's secrets to find the system secret-key
juju secrets --owner sentry-k8s
# rotate it; the charm re-derives config and Relay re-registers
juju secret-rotate <secret-id>
```

After rotation, confirm Relay re-registers against the upstream (it holds its
keypair in its own Juju secret and re-authenticates) and that both applications
settle back to `active`/`idle`.

## See also

- [Security hardening](security.md) — TLS, network isolation, Kafka auth.
- [Reference](reference-configuration.md) — all config options and actions.
