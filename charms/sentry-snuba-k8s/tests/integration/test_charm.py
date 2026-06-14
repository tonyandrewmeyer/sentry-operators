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
APP = "sentry-snuba-k8s"

CLICKHOUSE = "clickhouse-k8s"
KAFKA = "kafka-k8s"
REDIS = "redis-k8s"


def test_deploy_and_integrate(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy Snuba with its backends and confirm it reaches active/idle."""
    resources = {"snuba-image": METADATA["resources"]["snuba-image"]["upstream-source"]}
    juju.deploy(charm.resolve(), app=APP, resources=resources, config={"feature-complete": False})

    # Backends. ClickHouse is this repo's charm; the rest are Canonical charms.
    juju.deploy(CLICKHOUSE, channel="latest/edge")
    juju.deploy(KAFKA, channel="3/stable", config={"roles": "broker,controller"}, trust=True)
    juju.deploy(REDIS, channel="latest/edge", trust=True)

    # Snuba is blocked until every backend is integrated.
    juju.wait(lambda status: status.apps[APP].is_blocked, timeout=600)

    juju.integrate(APP, CLICKHOUSE)
    juju.integrate(APP, KAFKA)
    juju.integrate(APP, REDIS)

    juju.wait(jubilant.all_active, timeout=1800)


HEALTH_CHECK = (
    "import urllib.request, sys; "
    "sys.exit(0 if urllib.request.urlopen('http://localhost:1218/health').status == 200 else 1)"
)


def test_api_serves_health(juju: jubilant.Juju):
    """Snuba's HTTP API answers its health check on port 1218."""
    result = juju.exec(f"python3 -c {HEALTH_CHECK!r}", unit=f"{APP}/0")
    assert result.return_code == 0


def test_statsd_metrics_exposed(juju: jubilant.Juju):
    """The statsd-exporter sidecar re-exposes Snuba's metrics for Prometheus."""
    fetch = (
        "import urllib.request; "
        "print(urllib.request.urlopen('http://localhost:9102/metrics').read().decode())"
    )
    result = juju.exec(f"python3 -c {fetch!r}", unit=f"{APP}/0")
    assert result.return_code == 0
    # Real Snuba statsd series (not just the exporter's own metrics) must appear.
    assert "snuba" in result.stdout
