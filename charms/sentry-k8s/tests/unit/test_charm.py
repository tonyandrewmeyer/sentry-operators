# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the sentry-k8s charm."""

import dataclasses

import ops
import pytest
from ops import testing

import sentry
from charm import SENTRY_CONTAINER, SentryK8SCharm

# Exec matches by command prefix, so ["sentry"] covers both `sentry upgrade`
# and `sentry createuser`.
SENTRY_EXEC = testing.Exec(["sentry"], return_code=0, stdout="")


@pytest.fixture
def ctx():
    return testing.Context(SentryK8SCharm)


def _containers(exec_sentry=True):
    sentry_c = testing.Container(
        SENTRY_CONTAINER, can_connect=True, execs={SENTRY_EXEC} if exec_sentry else set()
    )
    return {
        sentry_c,
        testing.Container("taskbroker", can_connect=True),
        testing.Container("symbolicator", can_connect=True),
    }


def _wire(monkeypatch):
    monkeypatch.setattr(
        SentryK8SCharm,
        "_postgres",
        lambda self: sentry.PostgresInfo("pg", "5432", "sentry", "u", "p"),
    )
    monkeypatch.setattr(
        SentryK8SCharm, "_kafka", lambda self: sentry.KafkaInfo("kafka:9092", "ku", "kp")
    )
    monkeypatch.setattr(SentryK8SCharm, "_redis", lambda self: sentry.RedisInfo("redis", 6379))
    monkeypatch.setattr("charm.SnubaRequirer.url", property(lambda self: "http://snuba:1218"))


def test_blocked_without_integrations(ctx):
    state_in = testing.State(containers=_containers(exec_sentry=False), leader=True)
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    for backend in ("database", "kafka", "redis", "snuba"):
        assert backend in state_out.unit_status.message


def test_secret_key_generated_and_stored(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(containers=_containers(), relations={peer}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    peer_out = state_out.get_relation(peer.id)
    assert peer_out.local_app_data.get("secret-key-id")
    assert len(state_out.secrets) == 1


def test_services_started_when_ready(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(
        containers=_containers(),
        relations={peer},
        leader=True,
        config={"feature-complete": False},
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    services = state_out.get_container(SENTRY_CONTAINER).service_statuses
    assert services["web"] == ops.pebble.ServiceStatus.ACTIVE
    assert "events-consumer" in services
    assert "transactions-consumer" not in services
    # The retention-cleanup ticker runs regardless of the feature profile.
    assert services["cleanup-tick"] == ops.pebble.ServiceStatus.ACTIVE


def test_cleanup_notice_prunes_on_leader(ctx, monkeypatch):
    # The daily ticker raises a notice; the leader runs `sentry cleanup`. The
    # ["sentry"] exec is required, so an unmatched exec would fail the test.
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    notice = testing.Notice(key=sentry.CLEANUP_NOTICE_KEY)
    sentry_c = testing.Container(
        SENTRY_CONTAINER, can_connect=True, execs={SENTRY_EXEC}, notices=[notice]
    )
    containers = {
        sentry_c,
        testing.Container("taskbroker", can_connect=True),
        testing.Container("symbolicator", can_connect=True),
    }
    state_in = testing.State(containers=containers, relations={peer}, leader=True)

    # Succeeds only because the cleanup exec is available and gets run.
    ctx.run(ctx.on.pebble_custom_notice(sentry_c, notice), state_in)


def test_cleanup_notice_skipped_on_non_leader(ctx, monkeypatch):
    # A non-leader must not run cleanup: no exec is provided, so if the handler
    # tried to exec, the run would fail to find a matching command.
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    notice = testing.Notice(key=sentry.CLEANUP_NOTICE_KEY)
    sentry_c = testing.Container(SENTRY_CONTAINER, can_connect=True, notices=[notice])
    containers = {
        sentry_c,
        testing.Container("taskbroker", can_connect=True),
        testing.Container("symbolicator", can_connect=True),
    }
    state_in = testing.State(containers=containers, relations={peer}, leader=False)

    ctx.run(ctx.on.pebble_custom_notice(sentry_c, notice), state_in)


def test_smtp_password_read_from_secret(ctx, monkeypatch):
    # A secret-backed config option must be resolved and rendered into config.yml.
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    secret = testing.Secret({"password": "hunter2"})
    state_in = testing.State(
        containers=_containers(),
        relations={peer},
        secrets={secret},
        leader=True,
        config={"smtp-host": "smtp.example.com", "smtp-password": secret.id},
    )

    state_out = ctx.run(ctx.on.secret_changed(secret), state_in)

    fs = state_out.get_container(SENTRY_CONTAINER).get_filesystem(ctx)
    config_yml = (fs / "etc/sentry/config.yml").read_text()
    assert "mail.host: 'smtp.example.com'" in config_yml
    assert "mail.password: 'hunter2'" in config_yml


def test_symbolicator_stopped_when_disabled(ctx, monkeypatch):
    # Toggling enable-symbolicator true->false must actually stop the service.
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(containers=_containers(), relations={peer}, leader=True)

    enabled = ctx.run(ctx.on.config_changed(), state_in)
    assert (
        enabled.get_container("symbolicator").service_statuses["symbolicator"]
        == ops.pebble.ServiceStatus.ACTIVE
    )

    disabled = ctx.run(
        ctx.on.config_changed(),
        dataclasses.replace(enabled, config={"enable-symbolicator": False}),
    )
    assert (
        disabled.get_container("symbolicator").service_statuses["symbolicator"]
        == ops.pebble.ServiceStatus.INACTIVE
    )


def test_taskbroker_and_symbolicator_started(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(containers=_containers(), relations={peer}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert (
        state_out.get_container("taskbroker").service_statuses["taskbroker"]
        == ops.pebble.ServiceStatus.ACTIVE
    )
    assert (
        state_out.get_container("symbolicator").service_statuses["symbolicator"]
        == ops.pebble.ServiceStatus.ACTIVE
    )


def test_sentry_conf_pushed(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(containers=_containers(), relations={peer}, leader=True)

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    fs = state_out.get_container(SENTRY_CONTAINER).get_filesystem(ctx)
    conf = (fs / "etc/sentry/sentry.conf.py").read_text()
    assert "DATABASES" in conf
    assert "SCRAM-SHA-512" in conf


def test_publishes_web_url_to_relay(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    relay_rel = testing.Relation("sentry-relay")
    state_in = testing.State(containers=_containers(), relations={peer, relay_rel}, leader=True)

    state_out = ctx.run(ctx.on.relation_joined(relay_rel), state_in)

    data = state_out.get_relation(relay_rel.id).local_app_data
    assert data["web-url"].startswith("http://sentry-k8s.")
    assert data["web-url"].endswith(":9000")


def test_create_admin_action(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(containers=_containers(), relations={peer}, leader=True)

    ctx.run(ctx.on.action("create-admin", params={"email": "admin@example.com"}), state_in)

    assert ctx.action_results is not None
    assert ctx.action_results["email"] == "admin@example.com"
    assert "password-secret" in ctx.action_results


def test_get_admin_password_action(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(containers=_containers(), relations={peer}, leader=True)

    # Create the admin first, then look its credentials secret back up.
    created = ctx.run(
        ctx.on.action("create-admin", params={"email": "admin@example.com"}), state_in
    )
    ctx.run(ctx.on.action("get-admin-password", params={"email": "admin@example.com"}), created)

    assert ctx.action_results["email"] == "admin@example.com"
    assert ctx.action_results["password-secret"].startswith("secret:")


def test_get_admin_password_unknown_user_fails(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(containers=_containers(), relations={peer}, leader=True)

    with pytest.raises(testing.ActionFailed):
        ctx.run(
            ctx.on.action("get-admin-password", params={"email": "nobody@example.com"}), state_in
        )


def test_pause_stops_services_and_persists(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    state_in = testing.State(
        containers=_containers(), relations={peer}, leader=True, config={"feature-complete": False}
    )

    running = ctx.run(ctx.on.config_changed(), state_in)
    assert running.get_container(SENTRY_CONTAINER).service_statuses["web"] == (
        ops.pebble.ServiceStatus.ACTIVE
    )

    paused = ctx.run(ctx.on.action("pause"), running)

    assert ctx.action_results["status"] == "paused"
    assert paused.get_relation(peer.id).local_app_data.get("paused") == "true"
    assert paused.get_container(SENTRY_CONTAINER).service_statuses["web"] == (
        ops.pebble.ServiceStatus.INACTIVE
    )
    assert isinstance(paused.unit_status, testing.MaintenanceStatus)


def test_pause_survives_reconcile(ctx, monkeypatch):
    # A config change while paused must not restart the services.
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers", local_app_data={"paused": "true"})
    state_in = testing.State(
        containers=_containers(), relations={peer}, leader=True, config={"feature-complete": False}
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    services = state_out.get_container(SENTRY_CONTAINER).service_statuses
    assert all(s == ops.pebble.ServiceStatus.INACTIVE for s in services.values())


def test_resume_restarts_services(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers", local_app_data={"paused": "true"})
    state_in = testing.State(
        containers=_containers(), relations={peer}, leader=True, config={"feature-complete": False}
    )

    state_out = ctx.run(ctx.on.action("resume"), state_in)

    assert ctx.action_results["status"] == "resumed"
    assert "paused" not in state_out.get_relation(peer.id).local_app_data
    assert state_out.get_container(SENTRY_CONTAINER).service_statuses["web"] == (
        ops.pebble.ServiceStatus.ACTIVE
    )


# The provisioning script prints the DSN parts on stdout; ["python3"] matches it.
_PROVISION_EXEC = testing.Exec(
    ["python3"], return_code=0, stdout="PUBLIC_KEY=abc123\nPROJECT_ID=2\n"
)


def _containers_with_provision():
    sentry_c = testing.Container(
        SENTRY_CONTAINER, can_connect=True, execs={SENTRY_EXEC, _PROVISION_EXEC}
    )
    return {
        sentry_c,
        testing.Container("taskbroker", can_connect=True),
        testing.Container("symbolicator", can_connect=True),
    }


def test_publishes_dsn_on_request(ctx, monkeypatch):
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    relay = testing.Relation("sentry-relay", remote_app_name="sentry-relay-k8s")
    dsn = testing.Relation(
        "sentry-dsn",
        remote_app_name="demo-app",
        remote_app_data={"project-name": "demo-app", "platform": "python"},
    )
    state_in = testing.State(
        containers=_containers_with_provision(),
        relations={peer, relay, dsn},
        leader=True,
    )

    state_out = ctx.run(ctx.on.relation_changed(dsn), state_in)

    data = state_out.get_relation(dsn.id).local_app_data
    assert data["public-key"] == "abc123"
    assert data["project-id"] == "2"
    assert "abc123" in data["dsn"]
    assert "sentry-relay-k8s" in data["dsn"]
    assert data["dsn"].endswith(":3000/2")


def test_publishes_dsn_on_reconcile(ctx, monkeypatch):
    # The requirer integrated before Sentry was ready, so the dsn_requested event
    # came and went with nothing to publish. A later reconcile (here a plain
    # config_changed) must still provision and publish the DSN.
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    relay = testing.Relation("sentry-relay", remote_app_name="sentry-relay-k8s")
    dsn = testing.Relation(
        "sentry-dsn",
        remote_app_name="demo-app",
        remote_app_data={"project-name": "demo-app", "platform": "python"},
    )
    state_in = testing.State(
        containers=_containers_with_provision(),
        relations={peer, relay, dsn},
        leader=True,
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    data = state_out.get_relation(dsn.id).local_app_data
    assert data["public-key"] == "abc123"
    assert data["dsn"].endswith(":3000/2")


def test_no_dsn_published_without_a_relay(ctx, monkeypatch):
    # Events have nowhere to be ingested without a Relay, so no DSN is offered.
    _wire(monkeypatch)
    peer = testing.PeerRelation("sentry-peers")
    dsn = testing.Relation("sentry-dsn", remote_app_name="demo-app")
    state_in = testing.State(
        containers=_containers_with_provision(), relations={peer, dsn}, leader=True
    )

    state_out = ctx.run(ctx.on.relation_changed(dsn), state_in)

    assert state_out.get_relation(dsn.id).local_app_data == {}


def test_loki_alert_rules_are_valid():
    _assert_alert_rules("loki_alert_rules", topology_required=True)


def _assert_alert_rules(subdir: str, *, topology_required: bool) -> None:
    import pathlib

    import yaml

    rules_dir = pathlib.Path(__file__).parents[2] / "src" / subdir
    files = list(rules_dir.glob("*.yaml"))
    assert files, f"no alert rules found in {subdir}"
    total = 0
    for path in files:
        doc = yaml.safe_load(path.read_text())
        for group in doc["groups"]:
            for rule in group["rules"]:
                total += 1
                assert rule["alert"] and rule["expr"]
                assert rule["labels"]["severity"] in ("critical", "warning", "info")
                if topology_required:
                    assert "%%juju_topology%%" in rule["expr"]
    assert total
