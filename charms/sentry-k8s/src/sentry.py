# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Workload-specific logic for the Sentry application.

This module renders Sentry's configuration files and owns the catalogue of
processes that the ``sentry`` image can run (web, task workers, and the ingest /
post-process / subscription consumers), plus the configuration for the
``taskbroker`` and ``symbolicator`` sidecar containers.

It has no charming concerns, so it can be unit-tested on its own. Service
commands are transcribed from self-hosted Sentry's ``docker-compose.yml`` (tag
26.5.2); the ``--healthcheck-file-path`` flags are dropped because Pebble
manages liveness.
"""

from __future__ import annotations

import dataclasses

WEB_PORT = 9000
TASKBROKER_GRPC_PORT = 50051
SYMBOLICATOR_PORT = 3021

SENTRY_CONF_DIR = "/etc/sentry"
SENTRY_CONF_PY = f"{SENTRY_CONF_DIR}/sentry.conf.py"
SENTRY_CONFIG_YML = f"{SENTRY_CONF_DIR}/config.yml"
TASKBROKER_CONFIG_YML = "/etc/taskbroker/config.yml"
SYMBOLICATOR_CONFIG_YML = "/etc/symbolicator/config.yml"

SASL_SECURITY_PROTOCOL = "SASL_PLAINTEXT"
SASL_MECHANISM = "SCRAM-SHA-512"


@dataclasses.dataclass(frozen=True)
class PostgresInfo:
    """PostgreSQL connection details from the ``postgresql_client`` relation."""

    host: str
    port: str
    database: str
    username: str
    password: str


@dataclasses.dataclass(frozen=True)
class RedisInfo:
    """Redis connection details."""

    host: str
    port: int
    password: str = ""


@dataclasses.dataclass(frozen=True)
class KafkaInfo:
    """Kafka connection details from the ``kafka_client`` relation."""

    brokers: str
    username: str = ""
    password: str = ""


@dataclasses.dataclass(frozen=True)
class SentryService:
    """One Sentry process: a Pebble service name and its ``run`` arguments."""

    name: str
    args: str
    feature_complete: bool = False

    @property
    def command(self) -> str:
        """The full Pebble command (the image puts ``sentry`` on PATH)."""
        return f"sentry run {self.args}"


# Always-on (errors-only) Sentry processes.
_ALWAYS = (
    SentryService("web", "web"),
    SentryService("taskscheduler", "taskworker-scheduler"),
    SentryService(
        "taskworker",
        f"taskworker --concurrency={{concurrency}} "
        f"--rpc-host=localhost:{TASKBROKER_GRPC_PORT} --max-child-task-count=10000",
    ),
    SentryService("events-consumer", "consumer ingest-events --consumer-group ingest-consumer"),
    SentryService(
        "attachments-consumer",
        "consumer ingest-attachments --consumer-group ingest-consumer",
    ),
    SentryService(
        "post-process-forwarder-errors",
        "consumer --no-strict-offset-reset post-process-forwarder-errors "
        "--consumer-group post-process-forwarder "
        "--synchronize-commit-log-topic=snuba-commit-log "
        "--synchronize-commit-group=snuba-consumers",
    ),
    SentryService(
        "subscription-consumer-events",
        "consumer events-subscription-results --consumer-group query-subscription-consumer",
    ),
)

# Feature-complete adds transactions, metrics, replays, profiling, the issue
# platform, crons/uptime/feedback and their subscription consumers.
_FEATURE_COMPLETE = (
    SentryService(
        "transactions-consumer",
        "consumer ingest-transactions --consumer-group ingest-consumer",
        True,
    ),
    SentryService(
        "metrics-consumer", "consumer ingest-metrics --consumer-group metrics-consumer", True
    ),
    SentryService(
        "generic-metrics-consumer",
        "consumer ingest-generic-metrics --consumer-group generic-metrics-consumer",
        True,
    ),
    SentryService(
        "billing-metrics-consumer",
        "consumer billing-metrics-consumer --consumer-group billing-metrics-consumer",
        True,
    ),
    SentryService(
        "ingest-replay-recordings",
        "consumer ingest-replay-recordings --consumer-group ingest-replay-recordings",
        True,
    ),
    SentryService(
        "ingest-occurrences",
        "consumer ingest-occurrences --consumer-group ingest-occurrences",
        True,
    ),
    SentryService(
        "ingest-profiles", "consumer ingest-profiles --consumer-group ingest-profiles", True
    ),
    SentryService(
        "ingest-monitors", "consumer ingest-monitors --consumer-group ingest-monitors", True
    ),
    SentryService(
        "ingest-feedback-events",
        "consumer ingest-feedback-events --consumer-group ingest-feedback",
        True,
    ),
    SentryService(
        "process-spans",
        "consumer --no-strict-offset-reset process-spans --consumer-group process-spans",
        True,
    ),
    SentryService(
        "process-segments",
        "consumer --no-strict-offset-reset process-segments --consumer-group process-segments",
        True,
    ),
    SentryService(
        "monitors-clock-tick",
        "consumer monitors-clock-tick --consumer-group monitors-clock-tick",
        True,
    ),
    SentryService(
        "monitors-clock-tasks",
        "consumer monitors-clock-tasks --consumer-group monitors-clock-tasks",
        True,
    ),
    SentryService(
        "uptime-results", "consumer uptime-results --consumer-group uptime-results", True
    ),
    SentryService(
        "post-process-forwarder-transactions",
        "consumer --no-strict-offset-reset post-process-forwarder-transactions "
        "--consumer-group post-process-forwarder "
        "--synchronize-commit-log-topic=snuba-transactions-commit-log "
        "--synchronize-commit-group transactions_group",
        True,
    ),
    SentryService(
        "post-process-forwarder-issue-platform",
        "consumer --no-strict-offset-reset post-process-forwarder-issue-platform "
        "--consumer-group post-process-forwarder "
        "--synchronize-commit-log-topic=snuba-generic-events-commit-log "
        "--synchronize-commit-group generic_events_group",
        True,
    ),
    SentryService(
        "subscription-consumer-transactions",
        "consumer transactions-subscription-results --consumer-group query-subscription-consumer",
        True,
    ),
    SentryService(
        "subscription-consumer-metrics",
        "consumer metrics-subscription-results --consumer-group query-subscription-consumer",
        True,
    ),
    SentryService(
        "subscription-consumer-generic-metrics",
        "consumer generic-metrics-subscription-results "
        "--consumer-group query-subscription-consumer",
        True,
    ),
)

SERVICES: tuple[SentryService, ...] = _ALWAYS + _FEATURE_COMPLETE


def enabled_services(*, feature_complete: bool) -> tuple[SentryService, ...]:
    """Return the Sentry processes that should run for the configured profile."""
    if feature_complete:
        return SERVICES
    return _ALWAYS


def _kafka_common(kafka: KafkaInfo) -> dict[str, object]:
    """Build the shared librdkafka client config (with SASL when authenticated)."""
    common: dict[str, object] = {"bootstrap.servers": kafka.brokers}
    if kafka.username:
        common.update(
            {
                "security.protocol": SASL_SECURITY_PROTOCOL,
                "sasl.mechanism": SASL_MECHANISM,
                "sasl.username": kafka.username,
                "sasl.password": kafka.password,
            }
        )
    return common


def render_sentry_conf(
    *,
    postgres: PostgresInfo,
    redis: RedisInfo,
    kafka: KafkaInfo,
    feature_complete: bool,
    csrf_origins: list[str],
    behind_tls: bool,
) -> str:
    """Render ``sentry.conf.py`` from the relation data.

    The file inherits Sentry's server defaults and overrides only the
    connection settings and the few behaviours self-hosting needs. The default
    (Postgres-backed) nodestore is intentionally left in place.
    """
    common = _kafka_common(kafka)
    redis_url = f"redis://{redis.host}:{redis.port}"
    tls_block = (
        "SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')\n"
        "USE_X_FORWARDED_HOST = True\n"
        "SESSION_COOKIE_SECURE = True\n"
        "CSRF_COOKIE_SECURE = True\n"
        if behind_tls
        else ""
    )
    return f'''"""Charm-managed Sentry configuration."""

from sentry.conf.server import *  # noqa: F401,F403

DATABASES = {{
    "default": {{
        "ENGINE": "sentry.db.postgres",
        "NAME": {postgres.database!r},
        "USER": {postgres.username!r},
        "PASSWORD": {postgres.password!r},
        "HOST": {postgres.host!r},
        "PORT": {postgres.port!r},
    }}
}}

SENTRY_SINGLE_ORGANIZATION = True
SENTRY_SELF_HOSTED = True
SENTRY_SELF_HOSTED_ERRORS_ONLY = {not feature_complete!r}

SENTRY_OPTIONS["system.event-retention-days"] = int(env("SENTRY_EVENT_RETENTION_DAYS", "90"))
if env("SENTRY_SYSTEM_SECRET_KEY"):
    SENTRY_OPTIONS["system.secret-key"] = env("SENTRY_SYSTEM_SECRET_KEY")

SENTRY_OPTIONS["redis.clusters"] = {{
    "default": {{
        "hosts": {{
            0: {{
                "host": {redis.host!r},
                "port": {redis.port!r},
                "password": {redis.password!r},
                "db": 0,
            }}
        }}
    }}
}}

CACHES = {{
    "default": {{
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "{redis_url}/1",
        "TIMEOUT": 3600,
    }}
}}
SENTRY_CACHE = "sentry.cache.redis.RedisCache"
SENTRY_BUFFER = "sentry.buffer.redis.RedisBuffer"
SENTRY_QUOTAS = "sentry.quotas.redis.RedisQuota"
SENTRY_RATELIMITER = "sentry.ratelimits.redis.RedisRateLimiter"
SENTRY_TSDB = "sentry.tsdb.redissnuba.RedisSnubaTSDB"
SENTRY_SEARCH = "sentry.search.snuba.EventsDatasetSnubaSearchBackend"
SENTRY_DIGESTS = "sentry.digests.backends.redis.RedisBackend"

_KAFKA_COMMON = {common!r}
KAFKA_CLUSTERS = {{
    "default": {{
        "common": _KAFKA_COMMON,
        "producers": {{"compression.type": "lz4", "message.max.bytes": 50000000}},
        "consumers": {{}},
    }}
}}
SENTRY_EVENTSTREAM = "sentry.eventstream.kafka.KafkaEventStream"
SENTRY_EVENTSTREAM_OPTIONS = {{"producer_configuration": _KAFKA_COMMON}}

SENTRY_WEB_HOST = "0.0.0.0"
SENTRY_WEB_PORT = {WEB_PORT}
SENTRY_WEB_OPTIONS = {{
    "http": "0.0.0.0:{WEB_PORT}",
    "protocol": "uwsgi",
    "uwsgi-socket": None,
    "http-keepalive": 15,
    "http-chunked-input": True,
    "workers": 3,
    "threads": 4,
    "memory-report": False,
    "thunder-lock": True,
    "disable-logging": True,
    "buffer-size": 32768,
    "limit-post": 209715200,
}}

CSRF_TRUSTED_ORIGINS = {csrf_origins!r}
{tls_block}'''


def render_config_yml(
    *,
    url_prefix: str,
    enable_symbolicator: bool,
    mail: dict[str, str] | None = None,
) -> str:
    """Render Sentry's ``config.yml`` (the YAML options file)."""
    lines = [
        "# Charm-managed Sentry options.",
        f"system.url-prefix: {url_prefix!r}",
        "system.internal-url-prefix: 'http://localhost:9000'",
        "filestore.backend: 'filesystem'",
        "filestore.options:",
        "  location: '/data/files'",
    ]
    if enable_symbolicator:
        lines += [
            "symbolicator.enabled: true",
            "symbolicator.options:",
            f"  url: 'http://localhost:{SYMBOLICATOR_PORT}'",
        ]
    if mail and mail.get("host"):
        lines += [
            f"mail.host: {mail['host']!r}",
            f"mail.port: {int(mail.get('port', 25))}",
            f"mail.username: {mail.get('username', '')!r}",
            f"mail.password: {mail.get('password', '')!r}",
            f"mail.use-tls: {str(mail.get('use_tls', 'false')).lower() == 'true'}",
            f"mail.from: {mail.get('from', 'sentry@localhost')!r}",
        ]
    return "\n".join(lines) + "\n"


def sentry_environment(
    *, snuba_url: str, secret_key: str, event_retention_days: int
) -> dict[str, str]:
    """Environment shared by every ``sentry`` process."""
    return {
        "SENTRY_CONF": SENTRY_CONF_DIR,
        "SNUBA": snuba_url,
        "SENTRY_SYSTEM_SECRET_KEY": secret_key,
        "SENTRY_EVENT_RETENTION_DAYS": str(event_retention_days),
    }


def taskbroker_environment(kafka: KafkaInfo) -> dict[str, str]:
    """Environment that configures the taskbroker sidecar (figment ``__`` nesting)."""
    env = {
        "TASKBROKER_KAFKA_CLUSTERS__DEFAULT__ADDRESS": kafka.brokers,
        "TASKBROKER_KAFKA_TOPICS__TASKWORKER__CLUSTER": "default",
        "TASKBROKER_KAFKA_TOPICS__TASKWORKER__CONSUMER_GROUP": "taskworker",
        "TASKBROKER_KAFKA_DEADLETTER_TOPIC": "taskworker_dlq",
        "TASKBROKER_KAFKA_TOPICS__TASKWORKER_DLQ__CLUSTER": "default",
        "TASKBROKER_KAFKA_TOPICS__TASKWORKER_DLQ__CONSUMER_GROUP": "taskworker",
        "TASKBROKER_KAFKA_TOPICS__TASKWORKER_DLQ__PRODUCE_ONLY": "true",
        "TASKBROKER_DB_PATH": "/opt/sqlite/taskbroker-activations.sqlite",
        "TASKBROKER_GRPC_PORT": str(TASKBROKER_GRPC_PORT),
    }
    if kafka.username:
        env.update(
            {
                "TASKBROKER_KAFKA_CLUSTERS__DEFAULT__SECURITY_PROTOCOL": (
                    SASL_SECURITY_PROTOCOL.lower()
                ),
                "TASKBROKER_KAFKA_CLUSTERS__DEFAULT__SASL_MECHANISM": SASL_MECHANISM,
                "TASKBROKER_KAFKA_CLUSTERS__DEFAULT__SASL_USERNAME": kafka.username,
                "TASKBROKER_KAFKA_CLUSTERS__DEFAULT__SASL_PASSWORD": kafka.password,
            }
        )
    return env


def render_taskbroker_config() -> str:
    """Render a minimal taskbroker config file (clusters/topics come from env)."""
    return "# Charm-managed; cluster and topic settings are provided via env.\n{}\n"


def render_symbolicator_config() -> str:
    """Render symbolicator's config (mirrors self-hosted's ``config.example.yml``)."""
    return (
        "cache_dir: '/data'\n"
        f"bind: '0.0.0.0:{SYMBOLICATOR_PORT}'\n"
        "logging:\n"
        "  level: 'warn'\n"
        "sentry_dsn: null\n"
    )


def upgrade_command() -> list[str]:
    """Return the database migration command (Postgres migrations).

    We deliberately omit ``--create-kafka-topics``: in Sentry that flag does not
    actually create topics, it only *waits* for them to appear, relying on the
    broker's ``auto.create.topics.enable``. Canonical kafka-k8s disables
    auto-creation, so the charm creates the topics itself (see
    :func:`create_topics_command`).
    """
    return ["sentry", "upgrade", "--noinput"]


# Sentry expects ~120 Kafka topics (ingest-*, taskworker-*, outcomes-*, ...) to
# exist. Upstream relies on the broker auto-creating them; kafka-k8s does not,
# so we create them explicitly from Sentry's own topic registry, using the same
# admin client configuration (and therefore the same SASL credentials) Sentry
# would use itself. Replication follows the broker count (capped at 3).
_CREATE_TOPICS_SCRIPT = """
from sentry.runner import configure
configure()
from sentry_kafka_schemas import list_topics
from sentry.utils.kafka_config import (
    get_topic_definition_from_name,
    get_kafka_admin_cluster_options,
)
from confluent_kafka.admin import AdminClient, NewTopic

by_cluster = {}
for topic in list_topics():
    defn = get_topic_definition_from_name(topic)
    by_cluster.setdefault(defn["cluster"], set()).add(defn["real_topic_name"])

for cluster, names in by_cluster.items():
    admin = AdminClient(get_kafka_admin_cluster_options(cluster))
    replication = min(3, len(admin.list_topics(timeout=30).brokers)) or 1
    futures = admin.create_topics(
        [NewTopic(n, num_partitions=1, replication_factor=replication) for n in sorted(names)]
    )
    for name, future in futures.items():
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001
            if "already exists" not in str(exc).lower():
                raise
"""


def create_topics_command() -> list[str]:
    """Create every Kafka topic Sentry needs, idempotently.

    Runs in the Sentry container (which ships ``sentry_kafka_schemas`` and
    ``confluent_kafka``) with the same environment as the migration, so the
    admin client picks up the configured brokers and SASL credentials.
    """
    return ["python3", "-c", _CREATE_TOPICS_SCRIPT]


# Self-hosted Sentry has no built-in retention enforcement: upstream runs a
# nightly ``sentry cleanup --days N`` cron (see .reference/docker-compose.yml),
# which the app itself does not schedule. Pebble has no cron, so a tiny ticker
# service raises a Pebble custom notice once a day; the charm runs the actual
# cleanup in its notice handler, so the work is leader-gated, logged and only
# runs once across the application rather than blindly in every container.
CLEANUP_INTERVAL_SECONDS = 86400
CLEANUP_NOTICE_KEY = "sentry-k8s.charmhub.io/cleanup"


def cleanup_tick_command() -> str:
    """Return the Pebble command that raises the daily cleanup notice."""
    return (
        f"sh -c 'while true; do sleep {CLEANUP_INTERVAL_SECONDS}; "
        f"pebble notify {CLEANUP_NOTICE_KEY}; done'"
    )


def cleanup_command(days: int) -> list[str]:
    """Command to prune event data older than the retention window (in days)."""
    return ["sentry", "cleanup", "--days", str(days)]


def createuser_command(*, email: str, password: str, superuser: bool = True) -> list[str]:
    """Command to create (or update) the first admin user.

    ``--force-update`` makes the action idempotent: re-running it for an
    existing email resets that user rather than failing.
    """
    cmd = [
        "sentry",
        "createuser",
        "--email",
        email,
        "--password",
        password,
        "--no-input",
        "--force-update",
    ]
    if superuser:
        cmd.append("--superuser")
    return cmd


# Provisions (idempotently) the organization, team, project and key a related
# application needs, and prints the public key + project id so the charm can
# build a DSN. Any superusers are added to the organization so the projects are
# visible in the UI. Inputs come from the environment to avoid shell quoting.
_PROVISION_PROJECT_SCRIPT = """
import os
from sentry.runner import configure
configure()
from sentry.models.organization import Organization
from sentry.models.team import Team
from sentry.models.project import Project
from sentry.models.projectkey import ProjectKey
from sentry.models.organizationmember import OrganizationMember
try:
    from sentry.users.models.user import User
except Exception:  # noqa: BLE001 -- older import path
    from sentry.models import User

org_slug = os.environ["SENTRY_DSN_ORG"]
project_slug = os.environ["SENTRY_DSN_PROJECT"]
platform = os.environ.get("SENTRY_DSN_PLATFORM") or None

org, _ = Organization.objects.get_or_create(slug=org_slug, defaults={"name": org_slug})
team, _ = Team.objects.get_or_create(
    organization=org, slug=org_slug, defaults={"name": org_slug}
)
project, _ = Project.objects.get_or_create(
    organization=org, slug=project_slug, defaults={"name": project_slug, "platform": platform}
)
try:
    project.add_team(team)
except Exception:  # noqa: BLE001 -- already a member
    pass
for user in User.objects.filter(is_superuser=True):
    OrganizationMember.objects.get_or_create(
        organization=org, user_id=user.id, defaults={"role": "owner"}
    )
key = ProjectKey.objects.filter(project=project).first() or ProjectKey.objects.create(
    project=project
)
print("PUBLIC_KEY=" + key.public_key)
print("PROJECT_ID=" + str(project.id))
"""


def provision_project_command() -> list[str]:
    """Create (idempotently) a Sentry project + key and print its DSN parts.

    Reads ``SENTRY_DSN_ORG`` / ``SENTRY_DSN_PROJECT`` / ``SENTRY_DSN_PLATFORM``
    from the environment and prints ``PUBLIC_KEY=...`` and ``PROJECT_ID=...`` on
    stdout for the charm to parse.
    """
    return ["python3", "-c", _PROVISION_PROJECT_SCRIPT]
