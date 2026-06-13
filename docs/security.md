# Security hardening

This page is the hardening guidance referenced from the repository's
[`SECURITY.md`](../SECURITY.md). It covers transport security, secret handling,
network isolation, backend authentication and retention for a self-hosted Sentry
deployed with the `sentry-operators` charms.

## Transport security (TLS)

### Ingress

The Sentry UI/API and the Relay event-intake endpoint are exposed through the
`ingress` relation to `traefik-k8s`. **Terminate TLS at Traefik.** Relate
Traefik to a certificates provider so it serves HTTPS:

```bash
juju deploy self-signed-certificates    # or a real CA, e.g. lego/acme
juju integrate traefik-k8s self-signed-certificates
```

Use a publicly trusted certificate (ACME/Let's Encrypt via the `lego` charm, or
your own CA) for any internet-facing deployment — SDKs must reach the Relay DSN
over HTTPS.

### Kafka and PostgreSQL

Enable TLS on the data backends so traffic between the Sentry charms and the
backends is encrypted in transit, not just relying on the in-cluster network:

```bash
juju integrate kafka-k8s self-signed-certificates
juju integrate postgresql-k8s self-signed-certificates
```

The charms consume the connection details (including TLS material) over their
relations, so enabling TLS on the backend is picked up without reconfiguring the
Sentry charms by hand.

## Secrets

Generated secrets are stored in **Juju secrets**, never in charm config or in
relation databags in the clear:

- **`system.secret-key`** — generated once and held in the `sentry-k8s` peer
  secret; surfaced to Relay over the `sentry-relay` relation for registration.
- **Relay credentials** — Relay generates a keypair on first start and registers
  with the Sentry upstream; the `sentry-relay-k8s` charm stores that keypair in
  a Juju secret so it survives restarts.
- **Admin passwords** — the `create-admin` action writes the (generated or
  supplied) password to a Juju secret and returns its id; reveal with
  `juju show-secret --reveal <id>`.

Rotate the system secret key via Juju (`juju secret-rotate <id>`); see
[how-to-upgrade](how-to-upgrade.md#rotating-the-system-secret-key). Ensure the
Juju controller itself is backed up, since these secrets are part of controller
state.

Avoid putting sensitive values in plain config. The `smtp-password` option on
`sentry-k8s` is plain config — prefer an SMTP relay that does not require a
long-lived password, or restrict who can read the application's config.

## Network isolation

- Inter-component traffic (Sentry ↔ Snuba ↔ ClickHouse ↔ Kafka ↔ Redis ↔
  Postgres) stays on the **in-cluster pod network**. Only the `ingress` paths to
  Sentry and Relay should be reachable from outside the cluster.
- Apply Kubernetes **NetworkPolicies** so that, for example, only `sentry-k8s`
  and `sentry-snuba-k8s` can reach ClickHouse, and only the Sentry charms can
  reach PostgreSQL/Kafka/Redis.
- Do **not** expose ClickHouse, Kafka, Redis or PostgreSQL through ingress.
  ClickHouse in particular has no authentication tuned for external exposure in
  this single-node Snuba configuration.

## Backend authentication (SASL/SCRAM)

Kafka access is authenticated. The `kafka-k8s` charm provisions per-application
credentials over the `kafka_client` relation using **SASL/SCRAM**, so each of
`sentry-k8s`, `sentry-snuba-k8s` and `sentry-relay-k8s` gets its own scoped
username/password rather than a shared anonymous connection. Combine this with
Kafka TLS (above) so credentials are not sent in the clear. PostgreSQL and Redis
likewise hand out per-relation credentials through their charm relations.

## Retention

Limit how long event data — which may contain sensitive payloads — is kept:

```bash
juju config sentry-k8s event-retention-days=30
juju config sentry-snuba-k8s event-retention-days=30
```

Keep the two values equal so the Sentry-side retention and the ClickHouse TTLs
line up. Shorter retention reduces the amount of potentially sensitive data at
rest. Sentry's own data-scrubbing/PII features (server-side scrubbing in Relay)
should also be enabled at the project level for defence in depth.

## Upgrades

Keep the charms current so workload image CVEs are picked up — the underlying
OCI images are pinned by tag and digest and refreshed by bumping the charm. See
[how-to-upgrade](how-to-upgrade.md). To report a vulnerability in the charms
themselves, follow [`SECURITY.md`](../SECURITY.md).
