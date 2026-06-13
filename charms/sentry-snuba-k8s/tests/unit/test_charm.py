# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the sentry-snuba-k8s charm."""

import ops
import pytest
from charms.clickhouse_k8s.v0.clickhouse import ClickHouseConnection
from ops import testing

from charm import CONTAINER, KafkaConnection, SentrySnubaK8SCharm


@pytest.fixture
def ctx():
    return testing.Context(SentrySnubaK8SCharm)


def _wire_backends(monkeypatch, *, kafka_user=""):
    """Pretend all three backends are integrated and ready."""
    monkeypatch.setattr(
        "charm.ClickHouseRequirer.get_connection",
        lambda self: ClickHouseConnection("ch", 8123, 9000, "default"),
    )
    monkeypatch.setattr(
        SentrySnubaK8SCharm,
        "_kafka_connection",
        lambda self: KafkaConnection("kafka:9092", username=kafka_user, password="pw"),
    )
    monkeypatch.setattr(SentrySnubaK8SCharm, "_redis_connection", lambda self: ("redis", 6379))


def test_blocked_without_integrations(ctx):
    container = testing.Container(CONTAINER, can_connect=True)
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    for backend in ("clickhouse", "kafka", "redis"):
        assert backend in state_out.unit_status.message


def test_starts_services_when_ready(ctx, monkeypatch):
    _wire_backends(monkeypatch)
    container = testing.Container(CONTAINER, can_connect=True)
    # Non-leader so the bootstrap exec is skipped in this test.
    state_in = testing.State(
        containers={container}, leader=False, config={"feature-complete": False}
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    container_out = state_out.get_container(CONTAINER)
    assert container_out.service_statuses["snuba-api"] == ops.pebble.ServiceStatus.ACTIVE
    assert "errors-consumer" in container_out.service_statuses
    # Errors-only: feature-complete consumers are absent.
    assert "transactions-consumer" not in container_out.service_statuses


def test_feature_complete_runs_more_services(ctx, monkeypatch):
    _wire_backends(monkeypatch)
    container = testing.Container(CONTAINER, can_connect=True)
    state_in = testing.State(
        containers={container}, leader=False, config={"feature-complete": True}
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    services = state_out.get_container(CONTAINER).service_statuses
    assert "transactions-consumer" in services
    assert "eap-items-consumer" in services


def test_sasl_env_set_when_kafka_authenticated(ctx, monkeypatch):
    _wire_backends(monkeypatch, kafka_user="snuba-user")
    container = testing.Container(CONTAINER, can_connect=True)
    state_in = testing.State(
        containers={container}, leader=False, config={"feature-complete": False}
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    plan = state_out.get_container(CONTAINER).plan
    env = plan.services["snuba-api"].environment
    assert env["KAFKA_SASL_USERNAME"] == "snuba-user"
    assert env["KAFKA_SASL_MECHANISM"] == "SCRAM-SHA-512"


def test_publishes_url_to_requirer(ctx, monkeypatch):
    _wire_backends(monkeypatch)
    snuba_rel = testing.Relation("snuba")
    exec_mock = testing.Exec(["snuba", "bootstrap", "--force"], return_code=0, stdout="")
    container = testing.Container(CONTAINER, can_connect=True, execs={exec_mock})
    state_in = testing.State(
        containers={container},
        relations={snuba_rel},
        leader=True,
        config={"feature-complete": False},
    )

    state_out = ctx.run(ctx.on.relation_joined(snuba_rel), state_in)

    data = state_out.get_relation(snuba_rel.id).local_app_data
    assert data["url"].endswith(":1218")
    assert data["url"].startswith("http://sentry-snuba-k8s.")
