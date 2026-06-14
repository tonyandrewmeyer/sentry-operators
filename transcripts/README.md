# Development session transcripts

HTML transcripts of the Claude Code sessions that built and deployed this
charm set, generated with [`claude-code-transcripts`](https://pypi.org/project/claude-code-transcripts/)
(`uvx claude-code-transcripts json <session>.jsonl -o <dir>`). Open the
`index.html` in each directory in a browser.

- **[01-build-and-validate](01-build-and-validate/index.html)** — initial
  session: research of self-hosted Sentry 26.5.2, the four-charm topology
  decision, building clickhouse-k8s / sentry-snuba-k8s / sentry-relay-k8s /
  sentry-k8s, docs, Terraform, CI, and the first deploy/validation pass on a
  concierge-k8s model (where the port-opening bug was found).
- **[02-resume-and-deploy](02-resume-and-deploy/index.html)** — current
  session: resuming after a VM reboot and a directory rename, applying the
  workload port-opening fix and the observability dependency fix, then
  deploying the full Sentry core (postgres/redis/kafka/clickhouse/snuba/sentry)
  and working through the storage-mount, Kafka relation, and Kafka
  topic-creation issues to a healthy, event-serving stack.
- **[03-charm-excellence](03-charm-excellence/index.html)** — a polish pass
  taking the charms from "works" to production-grade: holistic-reconcile fixes
  (secret rotation, self-healing DSNs, symbolicator toggle), Loki/Prometheus
  alert rules, day-2 actions (get-admin-password / pause / resume), retention
  cleanup via a Pebble notice, Pebble health-check status handling, real metrics
  through a statsd-exporter sidecar, broadened integration tests, a dependency
  refresh, and Kafka consumer-lag plus Relay ingest alerts — validated against
  the live deployment.

These are a development record, not user documentation — see [`../docs`](../docs)
for that.
