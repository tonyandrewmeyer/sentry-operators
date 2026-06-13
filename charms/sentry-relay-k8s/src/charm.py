#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Charm Relay, the event-intake proxy of self-hosted Sentry."""

from __future__ import annotations

import dataclasses
import logging

import ops
from charms.data_platform_libs.v0.data_interfaces import KafkaRequires
from charms.sentry_k8s.v0.sentry_relay import SentryRelayRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import sentry_relay

logger = logging.getLogger(__name__)

CONTAINER = "relay"
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


class SentryRelayK8SCharm(ops.CharmBase):
    """Run and operate Relay, the Sentry event-intake proxy."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container(CONTAINER)
        self.kafka = KafkaRequires(
            self, relation_name=KAFKA_RELATION, topic=KAFKA_TOPIC, extra_user_roles="admin"
        )
        self.sentry = SentryRelayRequirer(self)
        self.ingress = IngressPerAppRequirer(self, port=sentry_relay.PORT, strip_prefix=True)

        for event in (
            self.on[CONTAINER].pebble_ready,
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
        event.add_status(ops.ActiveStatus())


if __name__ == "__main__":  # pragma: nocover
    ops.main(SentryRelayK8SCharm)
