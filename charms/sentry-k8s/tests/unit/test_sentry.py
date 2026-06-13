# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the Sentry workload module."""

import sentry

PG = sentry.PostgresInfo("pghost", "5432", "sentry", "user", "pw")
REDIS = sentry.RedisInfo("redishost", 6379)
KAFKA = sentry.KafkaInfo("kafka:9092", username="ku", password="kp")
KAFKA_NOAUTH = sentry.KafkaInfo("kafka:9092")


def _conf(**kw):
    defaults = {
        "postgres": PG,
        "redis": REDIS,
        "kafka": KAFKA,
        "feature_complete": True,
        "csrf_origins": ["https://sentry.example.com"],
        "behind_tls": True,
    }
    defaults.update(kw)
    return sentry.render_sentry_conf(**defaults)


def test_conf_sets_database():
    conf = _conf()
    assert "\"HOST\": 'pghost'" in conf
    assert "\"NAME\": 'sentry'" in conf
    assert "\"USER\": 'user'" in conf


def test_conf_uses_redis_cache_not_memcached():
    conf = _conf()
    assert "django.core.cache.backends.redis.RedisCache" in conf
    assert "redis://redishost:6379/1" in conf
    assert "memcached" not in conf


def test_conf_does_not_override_nodestore():
    # The default Postgres-backed nodestore must be left in place.
    assert "SENTRY_NODESTORE" not in _conf()
    assert "seaweedfs" not in _conf()


def test_conf_kafka_common_has_sasl():
    conf = _conf()
    assert "SASL_PLAINTEXT" in conf
    assert "SCRAM-SHA-512" in conf
    assert "'sasl.username': 'ku'" in conf
    assert '"common": _KAFKA_COMMON' in conf


def test_conf_kafka_without_auth_has_no_sasl():
    conf = _conf(kafka=KAFKA_NOAUTH)
    assert "SASL_PLAINTEXT" not in conf
    assert "bootstrap.servers" in conf


def test_conf_tls_block_only_when_behind_tls():
    assert "SECURE_PROXY_SSL_HEADER" in _conf(behind_tls=True)
    assert "SECURE_PROXY_SSL_HEADER" not in _conf(behind_tls=False)


def test_conf_errors_only_flag():
    assert "SENTRY_SELF_HOSTED_ERRORS_ONLY = True" in _conf(feature_complete=False)
    assert "SENTRY_SELF_HOSTED_ERRORS_ONLY = False" in _conf(feature_complete=True)


def test_config_yml_url_prefix_and_symbolicator():
    yml = sentry.render_config_yml(
        url_prefix="https://sentry.example.com", enable_symbolicator=True
    )
    assert "system.url-prefix: 'https://sentry.example.com'" in yml
    assert "symbolicator.enabled: true" in yml
    assert "filestore.backend: 'filesystem'" in yml


def test_config_yml_without_symbolicator_or_mail():
    yml = sentry.render_config_yml(url_prefix="http://x", enable_symbolicator=False)
    assert "symbolicator.enabled" not in yml
    assert "mail.host" not in yml


def test_config_yml_with_mail():
    yml = sentry.render_config_yml(
        url_prefix="http://x",
        enable_symbolicator=False,
        mail={"host": "smtp.example.com", "port": "587", "from": "s@x"},
    )
    assert "mail.host: 'smtp.example.com'" in yml
    assert "mail.port: 587" in yml


def test_services_errors_only_vs_feature_complete():
    errors_only = sentry.enabled_services(feature_complete=False)
    names = {s.name for s in errors_only}
    assert {"web", "taskworker", "taskscheduler", "events-consumer"} <= names
    assert "transactions-consumer" not in names
    full = sentry.enabled_services(feature_complete=True)
    assert {s.name for s in errors_only} < {s.name for s in full}


def test_web_service_command():
    web = next(s for s in sentry.SERVICES if s.name == "web")
    assert web.command == "sentry run web"


def test_taskbroker_env_includes_sasl():
    env = sentry.taskbroker_environment(KAFKA)
    assert env["TASKBROKER_KAFKA_CLUSTERS__DEFAULT__ADDRESS"] == "kafka:9092"
    assert env["TASKBROKER_KAFKA_CLUSTERS__DEFAULT__SASL_USERNAME"] == "ku"
    assert env["TASKBROKER_KAFKA_CLUSTERS__DEFAULT__SECURITY_PROTOCOL"] == "sasl_plaintext"


def test_taskbroker_env_without_auth():
    env = sentry.taskbroker_environment(KAFKA_NOAUTH)
    assert "TASKBROKER_KAFKA_CLUSTERS__DEFAULT__SASL_USERNAME" not in env


def test_symbolicator_config():
    cfg = sentry.render_symbolicator_config()
    assert "bind: '0.0.0.0:3021'" in cfg
    assert "cache_dir: '/data'" in cfg


def test_commands():
    # The migration runs database migrations only; topic creation is a separate
    # step because Sentry's --create-kafka-topics does not actually create them.
    assert sentry.upgrade_command() == ["sentry", "upgrade", "--noinput"]
    topics = sentry.create_topics_command()
    assert topics[0] == "python3" and topics[1] == "-c"
    assert "create_topics" in topics[2]
    cmd = sentry.createuser_command(email="a@b.c", password="pw")
    assert "--superuser" in cmd
    assert "--force-update" in cmd  # idempotent re-runs
    assert "a@b.c" in cmd


def test_environment():
    env = sentry.sentry_environment(
        snuba_url="http://snuba:1218", secret_key="k", event_retention_days=30
    )
    assert env["SNUBA"] == "http://snuba:1218"
    assert env["SENTRY_SYSTEM_SECRET_KEY"] == "k"
    assert env["SENTRY_EVENT_RETENTION_DAYS"] == "30"
