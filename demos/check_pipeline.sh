#!/usr/bin/env bash
# Prove the event travelled the whole pipeline: Relay -> Kafka -> Sentry
# consumers -> Postgres issue, and Sentry -> Kafka -> Snuba -> ClickHouse.
set -euo pipefail

MODEL="${MODEL:-testing}"
SECRET_KEY="${SECRET_KEY:-dfeb3245f4cb1f2a7e84d47587bb92c0d99d9489db178d38b72cfdd0a933f035}"
SNUBA="http://sentry-snuba-k8s.${MODEL}.svc.cluster.local:1218"
KCFG="/etc/kafka/client.properties"
KAFKA="/opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server localhost:9092 --command-config $KCFG"

echo "1. Kafka 'ingest-events' topic (Relay publishes here):"
juju ssh -m "$MODEL" --container kafka kafka-k8s/0 "$KAFKA --topic ingest-events 2>/dev/null" | sed 's/^/   /'

echo
echo "2. Issues recorded in Postgres (created by the Sentry consumers):"
juju ssh -m "$MODEL" --container sentry sentry-k8s/0 "SENTRY_CONF=/etc/sentry SENTRY_SYSTEM_SECRET_KEY=${SECRET_KEY} SNUBA=${SNUBA} python3 - <<PY 2>/dev/null
from sentry.runner import configure; configure()
from sentry.models.group import Group
for g in Group.objects.filter(project_id=1):
    print('   issue #%s  seen %sx  %s' % (g.id, g.times_seen, (g.title or '')[:64]))
PY"

echo
echo "3. Event rows stored in ClickHouse (written by the Snuba consumer):"
juju ssh -m "$MODEL" --container clickhouse clickhouse-k8s/0 "clickhouse-client --query \"SELECT count() AS events, max(timestamp) AS latest FROM default.errors_local WHERE project_id = 1 FORMAT PrettyCompactMonoBlock\" 2>/dev/null" | sed 's/^/   /'
