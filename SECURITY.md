# Security policy

## Supported versions

These charms are published to Charmhub on rolling channels. Security fixes are
delivered to the `latest/edge`, `latest/beta`, `latest/candidate` and
`latest/stable` channels as they are released. Only the most recent release on
each channel is supported; there are no long-term-support branches yet.

The charms package self-hosted Sentry, ClickHouse, Snuba and Relay. The
underlying workloads are consumed as upstream OCI images **pinned by tag and
digest**; security updates to those images are picked up by bumping the pinned
references and re-releasing the affected charm.

| Component | Supported version |
|-----------|-------------------|
| Sentry / Snuba / Relay images | 26.5.x (pinned per release) |
| ClickHouse image | 25.3.x Altinity (pinned per release) |
| Charm code | latest release on each channel |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report suspected vulnerabilities privately using GitHub's
[private vulnerability reporting](https://github.com/tonyandrewmeyer/sentry-operators/security/advisories/new)
for this repository, or by email to **tony.meyer@gmail.com** with the subject
line `SECURITY: sentry-operators`.

Please include:

- the affected charm(s) and channel/revision,
- a description of the vulnerability and its impact,
- steps to reproduce, and
- any suggested remediation.

You can expect an acknowledgement within **5 working days**. Once the report is
triaged we will agree a disclosure timeline with you, develop and test a fix,
release it to the affected channels, and credit you in the advisory unless you
prefer to remain anonymous.

## Security posture of the charms

- Generated secrets (Sentry's `system.secret-key`, Relay credentials, admin
  passwords) are stored in **Juju secrets**, never in charm config or in
  relation databags in the clear.
- Workload containers run the upstream images' non-root users where possible.
- Inter-component traffic stays on the in-cluster pod network; external access
  is via an ingress relation, where TLS termination should be configured.
- See [`docs/security.md`](docs/security.md) for hardening guidance (TLS,
  network policies, secret rotation, backups).
