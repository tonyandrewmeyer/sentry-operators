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
APP = "sentry-relay-k8s"

KAFKA = "kafka-k8s"
REDIS = "redis-k8s"


def test_deploy_and_integrate_backends(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy Relay with Kafka and Redis; it stays blocked waiting on Sentry."""
    resources = {"relay-image": METADATA["resources"]["relay-image"]["upstream-source"]}
    juju.deploy(charm.resolve(), app=APP, resources=resources)

    # Backends. Both are Canonical charms.
    juju.deploy(KAFKA, channel="3/stable", config={"roles": "broker,controller"}, trust=True)
    juju.deploy(REDIS, channel="latest/edge", trust=True)

    # Relay is blocked until every backend is integrated.
    juju.wait(lambda status: status.apps[APP].is_blocked, timeout=600)

    # Kafka and Redis relate cleanly.
    juju.integrate(APP, KAFKA)
    juju.integrate(APP, REDIS)

    # The Sentry charm isn't part of this test, so Relay stays blocked waiting on
    # the `sentry` integration. Confirm it reaches that state.
    def _blocked_on_sentry(status: jubilant.Status) -> bool:
        app = status.apps[APP]
        return app.is_blocked and "sentry" in (app.app_status.message or "")

    juju.wait(_blocked_on_sentry, timeout=600)
