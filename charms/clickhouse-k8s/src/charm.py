#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Charm a single-node ClickHouse server for self-hosted Sentry's Snuba."""

from __future__ import annotations

import logging

import ops
from charms.clickhouse_k8s.v0.clickhouse import ClickHouseProvider
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

import clickhouse

logger = logging.getLogger(__name__)

CONTAINER = "clickhouse"
SERVICE = "clickhouse-server"


@trace_charm(tracing_endpoint="_charm_tracing_endpoint")
class ClickHouseK8SCharm(ops.CharmBase):
    """Run and operate ClickHouse for Snuba."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container(CONTAINER)
        self.clickhouse = ClickHouseProvider(self)

        # Observability: forward Pebble logs to Loki, expose ClickHouse's native
        # Prometheus metrics, ship a Grafana dashboard, and trace the charm.
        self._logging = LogForwarder(self, relation_name="logging")
        self._metrics = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{clickhouse.METRICS_PORT}"]}]}],
        )
        self._grafana_dashboards = GrafanaDashboardProvider(
            self, relation_name="grafana-dashboard"
        )
        self._charm_tracing = TracingEndpointRequirer(
            self, relation_name="charm-tracing", protocols=["otlp_http"]
        )

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
        # Open the workload ports so the `<app>.<model>.svc` ClusterIP service
        # routes to them; a k8s Service only forwards ports the charm opens, so
        # without this cross-charm connections (e.g. Snuba -> ClickHouse:9000)
        # never reach the workload.
        self.unit.set_ports(
            clickhouse.HTTP_PORT, clickhouse.NATIVE_PORT, clickhouse.METRICS_PORT
        )
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

    @property
    def _charm_tracing_endpoint(self) -> str | None:
        """The Tempo otlp_http endpoint for charm self-tracing, if available."""
        if self._charm_tracing.is_ready():
            return self._charm_tracing.get_endpoint("otlp_http")
        return None

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
