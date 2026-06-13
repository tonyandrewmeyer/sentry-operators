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
    juju.deploy(charm.resolve(), app=APP, resources=_resources(), config={"feature-complete": False})

    # Data backends (Canonical charms).
    juju.deploy(POSTGRES, channel="14/stable", trust=True)
    juju.deploy(
        KAFKA, channel="3/stable", config={"roles": "broker,controller"}, trust=True
    )
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
