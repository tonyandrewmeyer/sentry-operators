# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Workload-specific logic for Snuba.

Snuba is configured entirely through environment variables (``SNUBA_SETTINGS``
selects the ``self_hosted`` profile, the rest point it at ClickHouse, Kafka and
Redis). This module owns the service catalogue and the environment, with no
charming concerns, so it can be unit-tested in isolation.

The service commands are transcribed from self-hosted Sentry's
``docker-compose.yml`` (tag 26.5.2). We drop the ``--health-check-file`` flags
because Pebble manages liveness and restarts instead of Docker healthchecks.
"""

from __future__ import annotations

import dataclasses

API_PORT = 1218


@dataclasses.dataclass(frozen=True)
class SnubaService:
    """One Snuba process: a Pebble service name and its ``snuba`` arguments."""

    name: str
    args: str
    feature_complete: bool = False

    @property
    def command(self) -> str:
        """The full Pebble command (the image puts ``snuba`` on PATH)."""
        return f"snuba {self.args}"


# The always-on services implement the errors-only profile: the query API, the
# consumers that write errors/outcomes/group-attributes into ClickHouse, the
# replacer that applies merges/deletes, and the alert-rule subscription executor.
_ALWAYS = (
    SnubaService("snuba-api", "api"),
    SnubaService(
        "errors-consumer",
        "rust-consumer --storage errors --consumer-group snuba-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
    ),
    SnubaService(
        "outcomes-consumer",
        "rust-consumer --storage outcomes_raw --consumer-group snuba-consumers "
        "--auto-offset-reset=earliest --max-batch-time-ms 750 --no-strict-offset-reset",
    ),
    SnubaService(
        "outcomes-billing-consumer",
        "rust-consumer --storage outcomes_raw --consumer-group snuba-consumers "
        "--auto-offset-reset=earliest --max-batch-time-ms 750 --no-strict-offset-reset "
        "--raw-events-topic outcomes-billing",
    ),
    SnubaService(
        "group-attributes-consumer",
        "rust-consumer --storage group_attributes "
        "--consumer-group snuba-group-attributes-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
    ),
    SnubaService(
        "replacer",
        "replacer --storage errors --auto-offset-reset=latest --no-strict-offset-reset",
    ),
    SnubaService(
        "subscription-scheduler-events",
        "subscriptions-scheduler-executor --dataset events --entity events "
        "--auto-offset-reset=latest --no-strict-offset-reset "
        "--consumer-group=snuba-events-subscriptions-consumers "
        "--followed-consumer-group=snuba-consumers "
        "--schedule-ttl=60 --stale-threshold-seconds=900",
    ),
)

# Feature-complete adds transactions, replays, the issue platform, the metrics
# and generic-metrics families, profiling and the events-analytics-platform.
_FEATURE_COMPLETE = (
    SnubaService(
        "transactions-consumer",
        "rust-consumer --storage transactions --consumer-group transactions_group "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "replays-consumer",
        "rust-consumer --storage replays --consumer-group snuba-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "issue-occurrence-consumer",
        "rust-consumer --storage search_issues --consumer-group generic_events_group "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "metrics-consumer",
        "rust-consumer --storage metrics_raw --consumer-group snuba-metrics-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "generic-metrics-distributions-consumer",
        "rust-consumer --storage generic_metrics_distributions_raw "
        "--consumer-group snuba-gen-metrics-distributions-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "generic-metrics-sets-consumer",
        "rust-consumer --storage generic_metrics_sets_raw "
        "--consumer-group snuba-gen-metrics-sets-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "generic-metrics-counters-consumer",
        "rust-consumer --storage generic_metrics_counters_raw "
        "--consumer-group snuba-gen-metrics-counters-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "generic-metrics-gauges-consumer",
        "rust-consumer --storage generic_metrics_gauges_raw "
        "--consumer-group snuba-gen-metrics-gauges-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 750 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "profiling-profiles-consumer",
        "rust-consumer --storage profiles --consumer-group snuba-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 1000 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "profiling-functions-consumer",
        "rust-consumer --storage functions_raw --consumer-group snuba-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 1000 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "profiling-profile-chunks-consumer",
        "rust-consumer --storage profile_chunks --consumer-group snuba-consumers "
        "--auto-offset-reset=latest --max-batch-time-ms 1000 --no-strict-offset-reset",
        True,
    ),
    SnubaService(
        "eap-items-consumer",
        "rust-consumer --storage eap_items --consumer-group eap_items_group "
        "--auto-offset-reset=latest --max-batch-time-ms 1000 --no-strict-offset-reset "
        "--use-rust-processor",
        True,
    ),
    SnubaService(
        "subscription-scheduler-transactions",
        "subscriptions-scheduler-executor --dataset transactions --entity transactions "
        "--auto-offset-reset=latest --no-strict-offset-reset "
        "--consumer-group=snuba-transactions-subscriptions-consumers "
        "--followed-consumer-group=transactions_group "
        "--schedule-ttl=60 --stale-threshold-seconds=900",
        True,
    ),
    SnubaService(
        "subscription-scheduler-metrics",
        "subscriptions-scheduler-executor --dataset metrics "
        "--entity metrics_sets --entity metrics_counters "
        "--auto-offset-reset=latest --no-strict-offset-reset "
        "--consumer-group=snuba-metrics-subscriptions-consumers "
        "--followed-consumer-group=snuba-metrics-consumers "
        "--schedule-ttl=60 --stale-threshold-seconds=900",
        True,
    ),
)

SERVICES: tuple[SnubaService, ...] = _ALWAYS + _FEATURE_COMPLETE


def enabled_services(*, feature_complete: bool) -> tuple[SnubaService, ...]:
    """Return the services that should run for the configured profile."""
    if feature_complete:
        return SERVICES
    return _ALWAYS


# librdkafka security values; SCRAM-SHA-512 matches kafka-k8s's default mechanism.
SASL_SECURITY_PROTOCOL = "SASL_PLAINTEXT"
SASL_MECHANISM = "SCRAM-SHA-512"


def build_environment(
    *,
    clickhouse_host: str,
    clickhouse_port: int,
    kafka_brokers: str,
    redis_host: str,
    redis_port: int,
    redis_password: str = "",
    kafka_username: str = "",
    kafka_password: str = "",
    event_retention_days: int = 90,
) -> dict[str, str]:
    """Build the environment shared by every Snuba process.

    Snuba's ``self_hosted`` profile reads its broker config from these
    environment variables, so SASL/SCRAM credentials for a Canonical
    ``kafka-k8s`` cluster are wired in here rather than via a settings file.
    """
    env = {
        "SNUBA_SETTINGS": "self_hosted",
        "CLICKHOUSE_HOST": clickhouse_host,
        "CLICKHOUSE_PORT": str(clickhouse_port),
        "DEFAULT_BROKERS": kafka_brokers,
        "REDIS_HOST": redis_host,
        "REDIS_PORT": str(redis_port),
        "SENTRY_EVENT_RETENTION_DAYS": str(event_retention_days),
        "UWSGI_MAX_REQUESTS": "10000",
        "UWSGI_DISABLE_LOGGING": "true",
    }
    if redis_password:
        env["REDIS_PASSWORD"] = redis_password
    if kafka_username:
        env["KAFKA_SECURITY_PROTOCOL"] = SASL_SECURITY_PROTOCOL
        env["KAFKA_SASL_MECHANISM"] = SASL_MECHANISM
        env["KAFKA_SASL_USERNAME"] = kafka_username
        env["KAFKA_SASL_PASSWORD"] = kafka_password
    return env


def bootstrap_command() -> list[str]:
    """Return the command that creates Snuba's Kafka topics.

    ``snuba bootstrap --force`` creates the Kafka topics but does NOT apply the
    ClickHouse schema migrations -- that is a separate step (see
    :func:`migrate_command`). It is idempotent, so it is safe to re-run.
    """
    return ["snuba", "bootstrap", "--force", "--no-migrate"]


def migrate_command() -> list[str]:
    """Return the command that applies Snuba's ClickHouse schema migrations.

    ``snuba bootstrap`` alone leaves every migration unapplied, so without this
    the storage tables (errors, outcomes, ...) never exist and event data is
    never written to ClickHouse. Idempotent: already-applied migrations are
    skipped.
    """
    return ["snuba", "migrations", "migrate", "--force"]
