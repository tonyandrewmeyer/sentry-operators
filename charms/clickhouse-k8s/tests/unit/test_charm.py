# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the clickhouse-k8s charm."""

import ops
import pytest
from ops import testing

from charm import CONTAINER, SERVICE, ClickHouseK8SCharm


@pytest.fixture
def ctx():
    return testing.Context(ClickHouseK8SCharm)


def _container(can_connect: bool = True) -> testing.Container:
    return testing.Container(CONTAINER, can_connect=can_connect)


def test_pebble_ready_starts_server(ctx, monkeypatch):
    monkeypatch.setattr("charm.clickhouse.get_version", lambda *a, **k: "25.3.6")
    monkeypatch.setattr("charm.clickhouse.is_ready", lambda *a, **k: True)
    container = _container()
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    container_out = state_out.get_container(CONTAINER)
    assert container_out.service_statuses[SERVICE] == ops.pebble.ServiceStatus.ACTIVE
    assert state_out.workload_version == "25.3.6"


def test_config_is_pushed(ctx, monkeypatch):
    monkeypatch.setattr("charm.clickhouse.get_version", lambda *a, **k: "25.3.6")
    monkeypatch.setattr("charm.clickhouse.is_ready", lambda *a, **k: True)
    container = _container()
    state_in = testing.State(
        containers={container},
        leader=True,
        config={"max-memory-usage-ratio": 0.5, "log-level": "error"},
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    fs = state_out.get_container(CONTAINER).get_filesystem(ctx)
    server_cfg = (fs / "etc/clickhouse-server/config.d/sentry.xml").read_text()
    assert "<listen_host>0.0.0.0</listen_host>" in server_cfg
    assert "<level>error</level>" in server_cfg
    assert "0.5" in server_cfg


def test_active_when_ready(ctx, monkeypatch):
    monkeypatch.setattr("charm.clickhouse.get_version", lambda *a, **k: "25.3.6")
    monkeypatch.setattr("charm.clickhouse.is_ready", lambda *a, **k: True)
    container = _container()
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    assert state_out.unit_status == testing.ActiveStatus()


def test_waiting_when_not_answering(ctx, monkeypatch):
    monkeypatch.setattr("charm.clickhouse.get_version", lambda *a, **k: None)
    monkeypatch.setattr("charm.clickhouse.is_ready", lambda *a, **k: False)
    container = _container()
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    assert state_out.unit_status == testing.WaitingStatus(
        "waiting for ClickHouse to accept queries"
    )


def test_cannot_connect_is_maintenance(ctx):
    container = _container(can_connect=False)
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, testing.MaintenanceStatus)


def test_publishes_connection_to_requirer(ctx, monkeypatch):
    monkeypatch.setattr("charm.clickhouse.get_version", lambda *a, **k: "25.3.6")
    monkeypatch.setattr("charm.clickhouse.is_ready", lambda *a, **k: True)
    relation = testing.Relation("clickhouse")
    container = _container()
    state_in = testing.State(containers={container}, relations={relation}, leader=True)

    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    data = state_out.get_relation(relation.id).local_app_data
    assert data["http-port"] == "8123"
    assert data["native-port"] == "9000"
    assert data["username"] == "default"
    assert data["host"].startswith("clickhouse-k8s.")


def test_opens_workload_ports(ctx, monkeypatch):
    # Other charms reach ClickHouse via the `<app>.<model>.svc` ClusterIP
    # service, which only forwards ports the charm explicitly opens.
    monkeypatch.setattr("charm.clickhouse.get_version", lambda *a, **k: "25.3.6")
    monkeypatch.setattr("charm.clickhouse.is_ready", lambda *a, **k: True)
    container = _container()
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    opened = {port.port for port in state_out.opened_ports}
    assert opened == {8123, 9000, 9363}


def test_opens_ports_even_when_container_down(ctx):
    # Ports are opened before the can-connect guard so the service routes as
    # soon as the workload comes up.
    container = _container(can_connect=False)
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    opened = {port.port for port in state_out.opened_ports}
    assert opened == {8123, 9000, 9363}


def test_non_leader_does_not_publish(ctx, monkeypatch):
    monkeypatch.setattr("charm.clickhouse.get_version", lambda *a, **k: "25.3.6")
    monkeypatch.setattr("charm.clickhouse.is_ready", lambda *a, **k: True)
    relation = testing.Relation("clickhouse")
    container = _container()
    state_in = testing.State(containers={container}, relations={relation}, leader=False)

    state_out = ctx.run(ctx.on.relation_joined(relation), state_in)

    assert state_out.get_relation(relation.id).local_app_data == {}
