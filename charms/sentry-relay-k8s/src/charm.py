#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Charm Relay, the event-intake proxy of self-hosted Sentry."""

from __future__ import annotations

import dataclasses
import logging

import ops
from charms.data_platform_libs.v0.data_interfaces import KafkaRequires
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.sentry_k8s.v0.sentry_relay import SentryRelayRequirer
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import sentry_relay

logger = logging.getLogger(__name__)

CONTAINER = "relay"
STATSD_EXPORTER_CONTAINER = "statsd-exporter"
KAFKA_RELATION = "kafka"
REDIS_RELATION = "redis"
SENTRY_RELATION = "sentry"
PEER_RELATION = "relay-peers"
# Relay registers itself with the Sentry upstream and creates topics, so the
# Kafka user needs broad permissions: request the admin role from kafka-k8s.
KAFKA_TOPIC = "sentry"

# Key under which the credentials secret URI is stored in the peer app databag.
_CREDENTIALS_SECRET_KEY = "credentials-secret-id"
# Field inside the secret holding the credentials JSON.
_CREDENTIALS_FIELD = "credentials"


@dataclasses.dataclass(frozen=True)
class KafkaConnection:
    """Kafka connection details, distilled from the kafka_client relation."""

    brokers: str
    username: str = ""
    password: str = ""


@trace_charm(tracing_endpoint="_charm_tracing_endpoint")
class SentryRelayK8SCharm(ops.CharmBase):
    """Run and operate Relay, the Sentry event-intake proxy."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container(CONTAINER)
        self.statsd_container = self.unit.get_container(STATSD_EXPORTER_CONTAINER)
        self.kafka = KafkaRequires(
            self, relation_name=KAFKA_RELATION, topic=KAFKA_TOPIC, extra_user_roles="admin"
        )
        self.sentry = SentryRelayRequirer(self)
        self.ingress = IngressPerAppRequirer(self, port=sentry_relay.PORT, strip_prefix=True)

        # Observability: forward Pebble logs to Loki, trace the charm, and scrape
        # the statsd-exporter sidecar that bridges Relay's statsd metrics to
        # Prometheus.
        self._logging = LogForwarder(self, relation_name="logging")
        self._metrics = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{sentry_relay.STATSD_METRICS_PORT}"]}]}],
        )
        self._charm_tracing = TracingEndpointRequirer(
            self, relation_name="charm-tracing", protocols=["otlp_http"]
        )

        for event in (
            self.on[CONTAINER].pebble_ready,
            self.on[STATSD_EXPORTER_CONTAINER].pebble_ready,
            self.on.config_changed,
            self.on.upgrade_charm,
            self.on[KAFKA_RELATION].relation_changed,
            self.on[KAFKA_RELATION].relation_broken,
            self.kafka.on.topic_created,
            self.kafka.on.bootstrap_server_changed,
            self.on[REDIS_RELATION].relation_changed,
            self.on[REDIS_RELATION].relation_broken,
            self.on[SENTRY_RELATION].relation_changed,
            self.on[SENTRY_RELATION].relation_broken,
            self.sentry.on.ready,
            self.sentry.on.gone,
            self.ingress.on.ready,
            self.ingress.on.revoked,
        ):
            framework.observe(event, self._reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on[CONTAINER].pebble_check_failed, self._on_check_failed)
        framework.observe(self.on[CONTAINER].pebble_check_recovered, self._on_check_recovered)

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
        if self._kafka_connection() is None:
            missing.append("kafka")
        if self._redis_connection() is None:
            missing.append("redis")
        if self.sentry.web_url is None:
            missing.append("sentry")
        return missing

    # -- credentials ----------------------------------------------------------

    def _ensure_credentials(self) -> str | None:
        """Return Relay's credentials JSON, generating and storing it once.

        The keypair is generated on the leader (via ``relay credentials
        generate``), stored in a peer-relation secret so it survives restarts
        and is shared across units, and read from that secret by non-leaders.
        Returns ``None`` if the credentials are not yet available (e.g. the peer
        relation has not formed, or generation failed); the caller should retry.
        """
        peers = self.model.get_relation(PEER_RELATION)
        if peers is None:
            return None
        secret_id = peers.data[self.app].get(_CREDENTIALS_SECRET_KEY)
        if secret_id is not None:
            secret = self.model.get_secret(id=secret_id)
            return secret.get_content(refresh=True)[_CREDENTIALS_FIELD]
        if not self.unit.is_leader():
            # Wait for the leader to generate and publish the credentials.
            return None
        try:
            process = self.container.exec(sentry_relay.credentials_generate_command())
            credentials, _ = process.wait_output()
        except ops.pebble.ExecError as exc:
            logger.warning("relay credentials generation failed (will retry): %s", exc)
            return None
        credentials = credentials.strip()
        secret = self.app.add_secret({_CREDENTIALS_FIELD: credentials})
        peers.data[self.app][_CREDENTIALS_SECRET_KEY] = secret.id  # type: ignore[assignment]
        return credentials

    # -- reconcile ------------------------------------------------------------

    def _reconcile(self, _: ops.EventBase) -> None:
        # Open the workload port so the `<app>.<model>.svc` ClusterIP service
        # routes to it (a k8s Service only forwards ports the charm opens);
        # ingress fronts Relay for event intake.
        self.unit.set_ports(sentry_relay.PORT)
        self._configure_statsd_exporter()
        if not self.container.can_connect():
            return
        kafka = self._kafka_connection()
        redis = self._redis_connection()
        web_url = self.sentry.web_url
        if kafka is None or redis is None or web_url is None:
            # Stop serving with stale config until every backend is back.
            self.container.add_layer("relay", {"services": {}}, combine=True)
            return

        credentials = self._ensure_credentials()
        if credentials is None:
            # Backends/peer not ready yet: retry on the next event.
            return

        self.container.push(sentry_relay.CREDENTIALS_PATH, credentials, make_dirs=True)
        config = sentry_relay.build_config(
            upstream=web_url,
            kafka_brokers=kafka.brokers,
            redis_host=redis[0],
            redis_port=redis[1],
            kafka_username=kafka.username,
            kafka_password=kafka.password,
            log_level=str(self.config["log-level"]),
        )
        self.container.push(sentry_relay.CONFIG_PATH, config, make_dirs=True)
        self.container.add_layer("relay", self._pebble_layer(), combine=True)
        self.container.replan()

    def _configure_statsd_exporter(self) -> None:
        if not self.statsd_container.can_connect():
            return
        self.statsd_container.add_layer(
            "statsd-exporter",
            {
                "summary": "statsd-exporter",
                "services": {
                    "statsd-exporter": {
                        "override": "replace",
                        "summary": "statsd to Prometheus exporter",
                        "command": sentry_relay.statsd_exporter_command(),
                        "startup": "enabled",
                    }
                },
            },
            combine=True,
        )
        self.statsd_container.replan()

    def _pebble_layer(self) -> ops.pebble.LayerDict:
        services: dict[str, ops.pebble.ServiceDict] = {
            "relay": {
                "override": "replace",
                "summary": "Relay event-intake proxy",
                "command": sentry_relay.run_command(),
                "startup": "enabled",
            }
        }
        return {
            "summary": "Relay",
            "description": "Relay event-intake proxy",
            "services": services,
            "checks": {
                "ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {
                        "url": f"http://localhost:{sentry_relay.PORT}"
                        f"{sentry_relay.HEALTHCHECK_PATH}"
                    },
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                }
            },
        }

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
            event.add_status(ops.MaintenanceStatus("waiting for Relay container"))
            return
        missing = self._missing()
        if missing:
            event.add_status(ops.BlockedStatus(f"missing integration(s): {', '.join(missing)}"))
            return
        services = self.container.get_services()
        if "relay" not in services or not services["relay"].is_running():
            event.add_status(ops.MaintenanceStatus("starting Relay"))
            return
        failing = self._failing_checks()
        if failing:
            event.add_status(ops.WaitingStatus(f"health check failing: {', '.join(failing)}"))
            return
        event.add_status(ops.ActiveStatus())

    def _on_check_failed(self, event: ops.PebbleCheckFailedEvent) -> None:
        logger.warning("Pebble health check %r is failing", event.info.name)

    def _on_check_recovered(self, event: ops.PebbleCheckRecoveredEvent) -> None:
        logger.info("Pebble health check %r recovered", event.info.name)

    def _failing_checks(self) -> list[str]:
        """Names of this unit's Pebble checks that are currently down."""
        if not self.container.can_connect():
            return []
        return [
            check.name
            for check in self.container.get_checks().values()
            if check.status != ops.pebble.CheckStatus.UP
        ]


if __name__ == "__main__":  # pragma: nocover
    ops.main(SentryRelayK8SCharm)
