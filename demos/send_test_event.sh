#!/usr/bin/env bash
# Send a real error event into the deployed Sentry through the Relay charm,
# exactly as an instrumented application would. Run against the validation
# model (juju model `testing`); PROJECT_KEY is the public DSN key of the
# `test-proj` project created during validation.
set -euo pipefail

MODEL="${MODEL:-testing}"
PROJECT_KEY="${PROJECT_KEY:-cf96f315bbd49aa67ae65788371e9f73}"
RELAY_HOST="sentry-relay-k8s.${MODEL}.svc.cluster.local:3000"
DSN="http://${PROJECT_KEY}@${RELAY_HOST}/1"

# The SDK runs inside the sentry container only because it is a convenient
# place that already has sentry-sdk installed and can resolve the Relay
# service; the event itself travels the real path Relay -> Kafka -> consumers.
juju ssh -m "$MODEL" --container sentry sentry-k8s/0 "python3 - <<PY 2>/dev/null
import sentry_sdk
sentry_sdk.init(dsn='${DSN}', traces_sample_rate=0, default_integrations=False, shutdown_timeout=20)
try:
    raise RuntimeError('Something went wrong in production (Juju charm demo)')
except Exception:
    event_id = sentry_sdk.capture_exception()
sentry_sdk.flush(timeout=20)
print('Sent event', event_id, 'to', '${RELAY_HOST}')
PY"
