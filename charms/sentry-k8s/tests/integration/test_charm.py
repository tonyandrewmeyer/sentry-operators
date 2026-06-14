# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/

import logging
import pathlib

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("charmcraft.yaml").read_text())
APP = "sentry-k8s"

POSTGRES = "postgresql-k8s"
KAFKA = "kafka-k8s"
REDIS = "redis-k8s"
CLICKHOUSE = "clickhouse-k8s"
SNUBA = "sentry-snuba-k8s"


def _resources():
    return {name: spec["upstream-source"] for name, spec in METADATA["resources"].items()}


def test_deploy_full_stack(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy Sentry with its whole backing stack and reach active/idle."""
    juju.deploy(
        charm.resolve(), app=APP, resources=_resources(), config={"feature-complete": False}
    )

    # Data backends (Canonical charms).
    juju.deploy(POSTGRES, channel="14/stable", trust=True)
    juju.deploy(KAFKA, channel="3/stable", config={"roles": "broker,controller"}, trust=True)
    juju.deploy(REDIS, channel="latest/edge", trust=True)
    # Kafka must accept Sentry's large (50 MB) messages.
    juju.config(KAFKA, {"message-max-bytes": "52428800"})
    # Postgres extensions Sentry's migrations expect.
    juju.config(POSTGRES, {"plugin_citext_enable": "true", "plugin_pg_trgm_enable": "true"})

    # Analytics tier (this repo's charms).
    juju.deploy(CLICKHOUSE, channel="latest/edge", trust=True)
    juju.deploy(SNUBA, channel="latest/edge", config={"feature-complete": False}, trust=True)
    juju.integrate(SNUBA, CLICKHOUSE)
    juju.integrate(SNUBA, KAFKA)
    juju.integrate(SNUBA, REDIS)

    # Sentry's own integrations.
    juju.integrate(APP, POSTGRES)
    juju.integrate(APP, KAFKA)
    juju.integrate(APP, REDIS)
    juju.integrate(APP, SNUBA)

    juju.wait(jubilant.all_active, timeout=3600, delay=15)


def test_create_admin_action(juju: jubilant.Juju):
    """The create-admin action provisions a superuser."""
    task = juju.run(f"{APP}/0", "create-admin", {"email": "admin@example.com"})
    assert task.results["email"] == "admin@example.com"
    assert task.results.get("password-secret")


def test_web_health(juju: jubilant.Juju):
    """Sentry web answers its health endpoint."""
    check = (
        "import urllib.request, sys; "
        "sys.exit(0 if urllib.request.urlopen('http://localhost:9000/_health/').status == 200 "
        "else 1)"
    )
    result = juju.exec(f"python3 -c {check!r}", unit=f"{APP}/0")
    assert result.return_code == 0


def test_statsd_metrics_exposed(juju: jubilant.Juju):
    """The statsd-exporter sidecar re-exposes Sentry's metrics for Prometheus."""
    fetch = (
        "import urllib.request; "
        "print(urllib.request.urlopen('http://localhost:9102/metrics').read().decode())"
    )
    result = juju.exec(f"python3 -c {fetch!r}", unit=f"{APP}/0")
    assert result.return_code == 0
    # Real Sentry statsd series (not just the exporter's own metrics) must appear.
    assert "sentry_" in result.stdout


def test_feature_complete_toggle_changes_services(juju: jubilant.Juju):
    """Enabling feature-complete starts the additional consumers."""
    assert "transactions-consumer" not in _sentry_services(juju)

    juju.config(APP, {"feature-complete": "true"})
    juju.wait(jubilant.all_active, timeout=900, delay=10)

    assert "transactions-consumer" in _sentry_services(juju)

    # Restore the errors-only profile for the remaining tests.
    juju.config(APP, {"feature-complete": "false"})
    juju.wait(jubilant.all_active, timeout=900, delay=10)


def test_pause_and_resume(juju: jubilant.Juju):
    """The pause action stops the services; resume brings them back."""
    juju.run(f"{APP}/0", "pause")
    juju.wait(
        lambda status: status.apps[APP].units[f"{APP}/0"].workload_status.current == "maintenance",
        timeout=300,
    )
    assert "web" not in _running_sentry_services(juju)

    juju.run(f"{APP}/0", "resume")
    juju.wait(jubilant.all_active, timeout=600, delay=10)
    assert "web" in _running_sentry_services(juju)


def test_backend_removal_blocks_then_recovers(juju: jubilant.Juju):
    """Removing a required backend blocks the charm; re-adding it recovers."""
    juju.remove_relation(APP, REDIS)
    juju.wait(
        lambda status: "redis" in status.apps[APP].units[f"{APP}/0"].workload_status.message,
        timeout=600,
    )

    juju.integrate(APP, REDIS)
    juju.wait(jubilant.all_active, timeout=900, delay=10)


# Pebble in each workload container has its own socket under /charm/containers.
_PEBBLE = "/charm/bin/pebble"
_SENTRY_SOCKET = "/charm/containers/sentry/pebble.socket"


def _pebble_service_rows(juju: jubilant.Juju) -> list[list[str]]:
    """Return the columns of each row of `pebble services` (Service Startup Current ...)."""
    result = juju.exec(f"PEBBLE_SOCKET={_SENTRY_SOCKET} {_PEBBLE} services", unit=f"{APP}/0")
    return [line.split() for line in result.stdout.splitlines()[1:] if line.strip()]


def _sentry_services(juju: jubilant.Juju) -> set[str]:
    """Return the names of the services in the Sentry container's Pebble plan."""
    return {row[0] for row in _pebble_service_rows(juju)}


def _running_sentry_services(juju: jubilant.Juju) -> set[str]:
    """Return the names of the currently active Sentry services (Current column)."""
    return {row[0] for row in _pebble_service_rows(juju) if row[2] == "active"}
