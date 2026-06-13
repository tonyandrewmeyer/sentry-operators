# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the sentry-relay-k8s charm."""

import ops
import pytest
import yaml
from ops import testing

from charm import CONTAINER, KafkaConnection, SentryRelayK8SCharm

CREDENTIALS = '{"secret_key":"s","public_key":"p","relay_id":"r"}'


@pytest.fixture
def ctx():
    return testing.Context(SentryRelayK8SCharm)


def _wire_backends(monkeypatch, *, kafka_user=""):
    """Pretend all backends are integrated and ready."""
    monkeypatch.setattr(
        SentryRelayK8SCharm,
        "_kafka_connection",
        lambda self: KafkaConnection("kafka:9092", username=kafka_user, password="pw"),
    )
    monkeypatch.setattr(SentryRelayK8SCharm, "_redis_connection", lambda self: ("redis", 6379))
    monkeypatch.setattr(
        "charm.SentryRelayRequirer.web_url",
        property(lambda self: "http://sentry-k8s.m.svc.cluster.local:9000/"),
    )


def _container():
    exec_mock = testing.Exec(
        ["relay", "credentials", "generate", "--stdout"],
        return_code=0,
        stdout=CREDENTIALS,
    )
    return testing.Container(CONTAINER, can_connect=True, execs={exec_mock})


def test_blocked_without_integrations(ctx):
    container = testing.Container(CONTAINER, can_connect=True)
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    for backend in ("kafka", "redis", "sentry"):
        assert backend in state_out.unit_status.message


def test_maintenance_without_container(ctx):
    container = testing.Container(CONTAINER, can_connect=False)
    state_in = testing.State(containers={container}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert isinstance(state_out.unit_status, testing.MaintenanceStatus)


def test_starts_relay_when_ready(ctx, monkeypatch):
    _wire_backends(monkeypatch)
    peers = testing.PeerRelation("relay-peers")
    state_in = testing.State(containers={_container()}, relations={peers}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    container_out = state_out.get_container(CONTAINER)
    assert container_out.service_statuses["relay"] == ops.pebble.ServiceStatus.ACTIVE
    assert state_out.unit_status == testing.ActiveStatus()


def test_config_pushed_when_ready(ctx, monkeypatch):
    _wire_backends(monkeypatch, kafka_user="relay-user")
    peers = testing.PeerRelation("relay-peers")
    state_in = testing.State(containers={_container()}, relations={peers}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    container_out = state_out.get_container(CONTAINER)
    fs = container_out.get_filesystem(ctx)
    config_file = fs / "work" / ".relay" / "config.yml"
    assert config_file.exists()
    config = yaml.safe_load(config_file.read_text())
    assert config["relay"]["upstream"] == "http://sentry-k8s.m.svc.cluster.local:9000/"
    assert config["processing"]["enabled"] is True
    pairs = {e["name"]: e["value"] for e in config["processing"]["kafka_config"]}
    assert pairs["sasl.username"] == "relay-user"
    # Credentials are pushed too.
    creds_file = fs / "work" / ".relay" / "credentials.json"
    assert creds_file.read_text() == CREDENTIALS


def test_credentials_stored_in_peer_secret(ctx, monkeypatch):
    _wire_backends(monkeypatch)
    peers = testing.PeerRelation("relay-peers")
    state_in = testing.State(containers={_container()}, relations={peers}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    peers_out = state_out.get_relation(peers.id)
    assert "credentials-secret-id" in peers_out.local_app_data
    # One secret holding the generated credentials.
    secret = next(iter(state_out.secrets))
    assert secret.latest_content["credentials"] == CREDENTIALS


def test_no_peer_relation_waits(ctx, monkeypatch):
    """Without the peer relation, credentials can't be stored, so no service starts."""
    _wire_backends(monkeypatch)
    state_in = testing.State(containers={_container()}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    container_out = state_out.get_container(CONTAINER)
    assert "relay" not in container_out.service_statuses


def test_non_leader_reads_credentials_from_secret(ctx, monkeypatch):
    _wire_backends(monkeypatch)
    secret = testing.Secret({"credentials": CREDENTIALS}, owner="app")
    peers = testing.PeerRelation(
        "relay-peers", local_app_data={"credentials-secret-id": secret.id}
    )
    # Non-leader: must not exec; reads the secret instead.
    container = testing.Container(CONTAINER, can_connect=True)
    state_in = testing.State(
        containers={container}, relations={peers}, secrets={secret}, leader=False
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    container_out = state_out.get_container(CONTAINER)
    assert container_out.service_statuses["relay"] == ops.pebble.ServiceStatus.ACTIVE
    fs = container_out.get_filesystem(ctx)
    assert (fs / "work" / ".relay" / "config.yml").exists()
