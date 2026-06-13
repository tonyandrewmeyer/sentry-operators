# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the Snuba workload module."""

import sentry_snuba


def test_errors_only_service_set():
    services = sentry_snuba.enabled_services(feature_complete=False)
    names = {s.name for s in services}
    assert "snuba-api" in names
    assert "errors-consumer" in names
    assert "replacer" in names
    # No feature-complete consumers when errors-only.
    assert "transactions-consumer" not in names
    assert all(not s.feature_complete for s in services)


def test_feature_complete_superset():
    errors_only = sentry_snuba.enabled_services(feature_complete=False)
    full = sentry_snuba.enabled_services(feature_complete=True)
    assert {s.name for s in errors_only} < {s.name for s in full}
    assert any(s.name == "transactions-consumer" for s in full)
    assert any(s.name == "eap-items-consumer" for s in full)


def test_service_command_prefixes_snuba():
    api = next(s for s in sentry_snuba.SERVICES if s.name == "snuba-api")
    assert api.command == "snuba api"
    errors = next(s for s in sentry_snuba.SERVICES if s.name == "errors-consumer")
    assert errors.command.startswith("snuba rust-consumer --storage errors")


def test_build_environment():
    env = sentry_snuba.build_environment(
        clickhouse_host="ch",
        clickhouse_port=9000,
        kafka_brokers="kafka:9092",
        redis_host="redis",
        redis_port=6379,
        event_retention_days=30,
    )
    assert env["SNUBA_SETTINGS"] == "self_hosted"
    assert env["CLICKHOUSE_HOST"] == "ch"
    assert env["CLICKHOUSE_PORT"] == "9000"
    assert env["DEFAULT_BROKERS"] == "kafka:9092"
    assert env["REDIS_HOST"] == "redis"
    assert env["SENTRY_EVENT_RETENTION_DAYS"] == "30"
    assert "REDIS_PASSWORD" not in env


def test_build_environment_with_redis_password():
    env = sentry_snuba.build_environment(
        clickhouse_host="ch",
        clickhouse_port=9000,
        kafka_brokers="kafka:9092",
        redis_host="redis",
        redis_port=6379,
        redis_password="s3cret",
    )
    assert env["REDIS_PASSWORD"] == "s3cret"


def test_build_environment_with_kafka_sasl():
    env = sentry_snuba.build_environment(
        clickhouse_host="ch",
        clickhouse_port=9000,
        kafka_brokers="kafka:9092",
        redis_host="redis",
        redis_port=6379,
        kafka_username="snuba-user",
        kafka_password="p@ss",
    )
    assert env["KAFKA_SECURITY_PROTOCOL"] == "SASL_PLAINTEXT"
    assert env["KAFKA_SASL_MECHANISM"] == "SCRAM-SHA-512"
    assert env["KAFKA_SASL_USERNAME"] == "snuba-user"
    assert env["KAFKA_SASL_PASSWORD"] == "p@ss"


def test_build_environment_without_kafka_auth_has_no_sasl():
    env = sentry_snuba.build_environment(
        clickhouse_host="ch",
        clickhouse_port=9000,
        kafka_brokers="kafka:9092",
        redis_host="redis",
        redis_port=6379,
    )
    assert "KAFKA_SASL_USERNAME" not in env


def test_bootstrap_command():
    # Bootstrap creates only Kafka topics; ClickHouse migrations are separate.
    assert sentry_snuba.bootstrap_command() == ["snuba", "bootstrap", "--force", "--no-migrate"]
    assert sentry_snuba.migrate_command() == ["snuba", "migrations", "migrate", "--force"]
