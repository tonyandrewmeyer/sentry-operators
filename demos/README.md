# Demos

[**end-to-end.md**](end-to-end.md) — an executable [showboat](https://pypi.org/project/showboat/)
document that sends a real error event into the deployed charms and follows it
through Relay → Kafka → the Sentry consumers → a Postgres issue and
Snuba → ClickHouse, ending with screenshots of the issue in the Sentry UI.

It runs against a live deployment (the validation model `juju model testing`,
with the `test-proj` project created during validation). The two helper scripts
are what the document executes:

- [`send_test_event.sh`](send_test_event.sh) — raise an exception and deliver it
  through the Relay charm, as an instrumented application would.
- [`check_pipeline.sh`](check_pipeline.sh) — show the event in the Kafka topic,
  the issue in Postgres, and the stored event rows in ClickHouse.

Re-run and re-verify the captured output with `showboat verify demos/end-to-end.md`.
