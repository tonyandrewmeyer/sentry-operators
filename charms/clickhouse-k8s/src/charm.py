#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Charm a single-node ClickHouse server for self-hosted Sentry's Snuba."""

from __future__ import annotations

import logging

import ops
from charms.clickhouse_k8s.v0.clickhouse import ClickHouseProvider

import clickhouse

logger = logging.getLogger(__name__)

CONTAINER = "clickhouse"
SERVICE = "clickhouse-server"


class ClickHouseK8SCharm(ops.CharmBase):
    """Run and operate ClickHouse for Snuba."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container(CONTAINER)
        self.clickhouse = ClickHouseProvider(self)

        # A single reconcile handler keeps the workload and relation data in
        # sync regardless of which event woke the charm.
        for event in (
            self.on[CONTAINER].pebble_ready,
            self.on.config_changed,
            self.on.upgrade_charm,
            self.on["clickhouse"].relation_joined,
            self.on["clickhouse"].relation_changed,
        ):
            framework.observe(event, self._reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

    def _reconcile(self, _: ops.EventBase) -> None:
        """Make the running workload match the charm's configuration."""
        if not self.container.can_connect():
            return
        self._push_config()
        self.container.add_layer(SERVICE, self._pebble_layer(), combine=True)
        self.container.replan()
        self._publish_connection()
        version = clickhouse.get_version()
        if version:
            self.unit.set_workload_version(version)

    def _push_config(self) -> None:
        """Render and push ClickHouse's drop-in configuration."""
        ratio = float(self.config["max-memory-usage-ratio"])  # type: ignore[arg-type]
        level = str(self.config["log-level"])
        self.container.push(
            clickhouse.SERVER_CONFIG_PATH,
            clickhouse.render_server_config(max_memory_ratio=ratio, log_level=level),
            make_dirs=True,
        )
        self.container.push(
            clickhouse.USERS_CONFIG_PATH,
            clickhouse.render_users_config(),
            make_dirs=True,
        )

    def _publish_connection(self) -> None:
        """Share the connection details with related requirers (e.g. Snuba)."""
        if not self.unit.is_leader():
            return
        if not clickhouse.is_ready():
            return
        self.clickhouse.publish(
            host=self._service_fqdn,
            http_port=clickhouse.HTTP_PORT,
            native_port=clickhouse.NATIVE_PORT,
            username="default",
        )

    @property
    def _service_fqdn(self) -> str:
        """The in-cluster DNS name other charms use to reach this application."""
        return f"{self.app.name}.{self.model.name}.svc.cluster.local"

    def _pebble_layer(self) -> ops.pebble.LayerDict:
        return {
            "summary": "ClickHouse server",
            "description": "Single-node ClickHouse for Snuba",
            "services": {
                SERVICE: {
                    "override": "replace",
                    "summary": "clickhouse-server",
                    # The image's entrypoint fixes data-dir ownership and then
                    # execs the server as the clickhouse user.
                    "command": "/entrypoint.sh",
                    "startup": "enabled",
                }
            },
            "checks": {
                "ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": f"http://localhost:{clickhouse.HTTP_PORT}/ping"},
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                }
            },
        }

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        if not self.container.can_connect():
            event.add_status(ops.MaintenanceStatus("waiting for ClickHouse container"))
            return
        services = self.container.get_services()
        if SERVICE not in services or not services[SERVICE].is_running():
            event.add_status(ops.MaintenanceStatus("starting ClickHouse"))
            return
        if not clickhouse.is_ready():
            event.add_status(ops.WaitingStatus("waiting for ClickHouse to accept queries"))
            return
        event.add_status(ops.ActiveStatus())


if __name__ == "__main__":  # pragma: nocover
    ops.main(ClickHouseK8SCharm)
