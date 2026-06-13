#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Charm Snuba, the search and analytics service of self-hosted Sentry."""

from __future__ import annotations

import dataclasses
import logging

import ops
from charms.clickhouse_k8s.v0.clickhouse import ClickHouseConnection, ClickHouseRequirer
from charms.data_platform_libs.v0.data_interfaces import KafkaRequires
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.sentry_snuba_k8s.v0.snuba import SnubaProvider
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

import sentry_snuba

logger = logging.getLogger(__name__)

CONTAINER = "snuba"
KAFKA_RELATION = "kafka"
REDIS_RELATION = "redis"
# Snuba/Sentry create dozens of topics on bootstrap, so the Kafka user needs
# broad permissions: request the admin role from kafka-k8s.
KAFKA_TOPIC = "sentry"


@dataclasses.dataclass(frozen=True)
class KafkaConnection:
    """Kafka connection details, distilled from the kafka_client relation."""

    brokers: str
    username: str = ""
    password: str = ""


@trace_charm(tracing_endpoint="_charm_tracing_endpoint")
class SentrySnubaK8SCharm(ops.CharmBase):
    """Run and operate Snuba (API + consumers) over ClickHouse."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container(CONTAINER)
        self.clickhouse = ClickHouseRequirer(self)
        self.kafka = KafkaRequires(
            self, relation_name=KAFKA_RELATION, topic=KAFKA_TOPIC, extra_user_roles="admin"
        )
        self.snuba = SnubaProvider(self)

        # Observability: forward Pebble logs to Loki, ship a log-based Grafana
        # dashboard, and trace the charm. Snuba emits statsd (not Prometheus)
        # metrics, so there is no metrics-endpoint scrape here.
        self._logging = LogForwarder(self, relation_name="logging")
        self._grafana_dashboards = GrafanaDashboardProvider(
            self, relation_name="grafana-dashboard"
        )
        self._charm_tracing = TracingEndpointRequirer(
            self, relation_name="charm-tracing", protocols=["otlp_http"]
        )

        for event in (
            self.on[CONTAINER].pebble_ready,
            self.on.config_changed,
            self.on.upgrade_charm,
            self.clickhouse.on.ready,
            self.clickhouse.on.gone,
            self.on[KAFKA_RELATION].relation_changed,
            self.on[KAFKA_RELATION].relation_broken,
            self.kafka.on.topic_created,
            self.kafka.on.bootstrap_server_changed,
            self.on[REDIS_RELATION].relation_changed,
            self.on[REDIS_RELATION].relation_broken,
            self.on["snuba"].relation_joined,
        ):
            framework.observe(event, self._reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

    # -- relation data helpers ------------------------------------------------

    def _kafka_connection(self) -> KafkaConnection | None:
        relation = self.model.get_relation(KAFKA_RELATION)
        if relation is None:
            return None
        data = self.kafka.fetch_relation_data().get(relation.id, {})
        brokers = data.get("endpoints")
        if not brokers:
            return None
        return KafkaConnection(
            brokers=brokers,
            username=data.get("username", ""),
            password=data.get("password", ""),
        )

    def _redis_connection(self) -> tuple[str, int] | None:
        relation = self.model.get_relation(REDIS_RELATION)
        if relation is None:
            return None
        for unit in relation.units:
            host = relation.data[unit].get("hostname")
            port = relation.data[unit].get("port")
            if host and port:
                return host, int(port)
        return None

    def _missing(self) -> list[str]:
        """Return the names of integrations that are not yet ready."""
        missing = []
        if self.clickhouse.get_connection() is None:
            missing.append("clickhouse")
        if self._kafka_connection() is None:
            missing.append("kafka")
        if self._redis_connection() is None:
            missing.append("redis")
        return missing

    # -- reconcile ------------------------------------------------------------

    def _reconcile(self, _: ops.EventBase) -> None:
        # Open the API port so the `<app>.<model>.svc` ClusterIP service routes
        # to it (a k8s Service only forwards ports the charm opens); without
        # this, Sentry cannot reach the Snuba API.
        self.unit.set_ports(sentry_snuba.API_PORT)
        if not self.container.can_connect():
            return
        clickhouse = self.clickhouse.get_connection()
        kafka = self._kafka_connection()
        redis = self._redis_connection()
        if clickhouse is None or kafka is None or redis is None:
            # Stop serving with stale config until every backend is back.
            self.container.add_layer("snuba", {"services": {}}, combine=True)
            return

        if self.unit.is_leader():
            self._bootstrap(clickhouse, kafka, redis)
        self.container.add_layer(
            "snuba", self._pebble_layer(clickhouse, kafka, redis), combine=True
        )
        self.container.replan()
        self._publish_url()

    def _environment(
        self, clickhouse: ClickHouseConnection, kafka: KafkaConnection, redis: tuple[str, int]
    ) -> dict[str, str]:
        return sentry_snuba.build_environment(
            clickhouse_host=clickhouse.host,
            clickhouse_port=clickhouse.native_port,
            kafka_brokers=kafka.brokers,
            kafka_username=kafka.username,
            kafka_password=kafka.password,
            redis_host=redis[0],
            redis_port=redis[1],
            event_retention_days=int(self.config["event-retention-days"]),  # type: ignore[arg-type]
        )

    def _bootstrap(
        self, clickhouse: ClickHouseConnection, kafka: KafkaConnection, redis: tuple[str, int]
    ) -> None:
        """Create Kafka topics and ClickHouse schema (idempotent)."""
        env = self._environment(clickhouse, kafka, redis)
        logger.info("Running snuba bootstrap (Kafka topics)")
        try:
            self.container.exec(
                sentry_snuba.bootstrap_command(), environment=env, timeout=600
            ).wait_output()
        except ops.pebble.ExecError as exc:
            logger.warning("snuba bootstrap failed (will retry): %s", exc)
        logger.info("Running snuba migrations (ClickHouse schema)")
        try:
            self.container.exec(
                sentry_snuba.migrate_command(), environment=env, timeout=600
            ).wait_output()
        except ops.pebble.ExecError as exc:
            logger.warning("snuba migrations failed (will retry): %s", exc)

    def _pebble_layer(
        self, clickhouse: ClickHouseConnection, kafka: KafkaConnection, redis: tuple[str, int]
    ) -> ops.pebble.LayerDict:
        env = self._environment(clickhouse, kafka, redis)
        feature_complete = bool(self.config["feature-complete"])
        services: dict[str, ops.pebble.ServiceDict] = {
            service.name: {
                "override": "replace",
                "summary": service.name,
                "command": service.command,
                "startup": "enabled",
                "environment": env,
                "after": ["snuba-api"] if service.name != "snuba-api" else [],
            }
            for service in sentry_snuba.enabled_services(feature_complete=feature_complete)
        }
        return {
            "summary": "Snuba",
            "description": "Snuba API and consumers",
            "services": services,
            "checks": {
                "api-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": f"http://localhost:{sentry_snuba.API_PORT}/health"},
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                }
            },
        }

    def _publish_url(self) -> None:
        url = f"http://{self.app.name}.{self.model.name}.svc.cluster.local:{sentry_snuba.API_PORT}"
        self.snuba.publish(url=url)

    # -- tracing --------------------------------------------------------------

    @property
    def _charm_tracing_endpoint(self) -> str | None:
        """The Tempo otlp_http endpoint for charm self-tracing, if available."""
        if self._charm_tracing.is_ready():
            return self._charm_tracing.get_endpoint("otlp_http")
        return None

    # -- status ---------------------------------------------------------------

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        if not self.container.can_connect():
            event.add_status(ops.MaintenanceStatus("waiting for Snuba container"))
            return
        missing = self._missing()
        if missing:
            event.add_status(ops.BlockedStatus(f"missing integration(s): {', '.join(missing)}"))
            return
        services = self.container.get_services()
        if "snuba-api" not in services or not services["snuba-api"].is_running():
            event.add_status(ops.MaintenanceStatus("starting Snuba"))
            return
        event.add_status(ops.ActiveStatus())


if __name__ == "__main__":  # pragma: nocover
    ops.main(SentrySnubaK8SCharm)
