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
APP = "clickhouse-k8s"


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm and wait for it to go active."""
    resources = {
        "clickhouse-image": METADATA["resources"]["clickhouse-image"]["upstream-source"]
    }
    juju.deploy(charm.resolve(), app=APP, resources=resources)
    juju.wait(jubilant.all_active, timeout=900)


def test_workload_version_is_set(juju: jubilant.Juju):
    """ClickHouse reports its version once it is answering queries."""
    version = juju.status().apps[APP].version
    assert version, "expected a non-empty ClickHouse version"
    assert version.startswith("25."), f"unexpected ClickHouse version: {version}"
