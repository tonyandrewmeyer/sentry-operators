#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Charm the Sentry application: web, task workers and the ingest consumers."""

from __future__ import annotations

import logging
import secrets

import ops
from charmlibs.interfaces.sentry_dsn import SentryDsnProvider
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires, KafkaRequires
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.sentry_k8s.v0.sentry_relay import SentryRelayProvider
from charms.sentry_snuba_k8s.v0.snuba import SnubaRequirer
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import sentry

logger = logging.getLogger(__name__)

SENTRY_CONTAINER = "sentry"
TASKBROKER_CONTAINER = "taskbroker"
SYMBOLICATOR_CONTAINER = "symbolicator"

DATABASE_RELATION = "database"
KAFKA_RELATION = "kafka"
REDIS_RELATION = "redis"
RELAY_RELATION = "sentry-relay"
DSN_RELATION = "sentry-dsn"
PEER_RELATION = "sentry-peers"

DATABASE_NAME = "sentry"
KAFKA_TOPIC = "sentry"
SECRET_LABEL = "sentry-secret-key"
# The Relay charm's workload port; events in a published DSN are sent here.
RELAY_PORT = 3000
# The shared Sentry organization that DSN-integrated apps' projects live under.
DSN_ORGANIZATION = "sentry"


@trace_charm(tracing_endpoint="_charm_tracing_endpoint")
class SentryK8SCharm(ops.CharmBase):
    """Operate the Sentry application tier."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.sentry_container = self.unit.get_container(SENTRY_CONTAINER)
        self.taskbroker_container = self.unit.get_container(TASKBROKER_CONTAINER)
        self.symbolicator_container = self.unit.get_container(SYMBOLICATOR_CONTAINER)

        # Observability: forward all containers' Pebble logs to Loki, ship a
        # log-based Grafana dashboard, and trace the charm. Sentry emits statsd
        # (not Prometheus) metrics, so there is no metrics-endpoint scrape here.
        self._logging = LogForwarder(self, relation_name="logging")
        self._grafana_dashboards = GrafanaDashboardProvider(
            self, relation_name="grafana-dashboard"
        )
        self._charm_tracing = TracingEndpointRequirer(
            self, relation_name="charm-tracing", protocols=["otlp_http"]
        )

        self.database = DatabaseRequires(
            self, relation_name=DATABASE_RELATION, database_name=DATABASE_NAME
        )
        self.kafka = KafkaRequires(
            self, relation_name=KAFKA_RELATION, topic=KAFKA_TOPIC, extra_user_roles="admin"
        )
        self.snuba = SnubaRequirer(self)
        self.relay = SentryRelayProvider(self, relation_name=RELAY_RELATION)
        self.sentry_dsn = SentryDsnProvider(self, relation_name=DSN_RELATION)
        self.ingress = IngressPerAppRequirer(self, port=sentry.WEB_PORT, strip_prefix=True)

        for event in (
            self.on[SENTRY_CONTAINER].pebble_ready,
            self.on[TASKBROKER_CONTAINER].pebble_ready,
            self.on[SYMBOLICATOR_CONTAINER].pebble_ready,
            self.on.config_changed,
            self.on.upgrade_charm,
            self.on[PEER_RELATION].relation_created,
            self.database.on.database_created,
            self.database.on.endpoints_changed,
            self.on[KAFKA_RELATION].relation_changed,
            self.on[KAFKA_RELATION].relation_broken,
            self.kafka.on.topic_created,
            self.kafka.on.bootstrap_server_changed,
            self.on[REDIS_RELATION].relation_changed,
            self.on[REDIS_RELATION].relation_broken,
            self.snuba.on.ready,
            self.snuba.on.gone,
            self.on["sentry-relay"].relation_joined,
            self.ingress.on.ready,
            self.ingress.on.revoked,
        ):
            framework.observe(event, self._reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on.create_admin_action, self._on_create_admin)
        framework.observe(self.sentry_dsn.on.dsn_requested, self._on_dsn_requested)

    # -- relation data --------------------------------------------------------

    def _postgres(self) -> sentry.PostgresInfo | None:
        relation = self.model.get_relation(DATABASE_RELATION)
        if relation is None:
            return None
        data = self.database.fetch_relation_data().get(relation.id, {})
        endpoints = data.get("endpoints")
        if not endpoints:
            return None
        host, _, port = endpoints.split(",")[0].partition(":")
        return sentry.PostgresInfo(
            host=host,
            port=port or "5432",
            database=data.get("database", DATABASE_NAME),
            username=data.get("username", ""),
            password=data.get("password", ""),
        )

    def _kafka(self) -> sentry.KafkaInfo | None:
        relation = self.model.get_relation(KAFKA_RELATION)
        if relation is None:
            return None
        data = self.kafka.fetch_relation_data().get(relation.id, {})
        brokers = data.get("endpoints")
        if not brokers:
            return None
        return sentry.KafkaInfo(
            brokers=brokers,
            username=data.get("username", ""),
            password=data.get("password", ""),
        )

    def _redis(self) -> sentry.RedisInfo | None:
        relation = self.model.get_relation(REDIS_RELATION)
        if relation is None:
            return None
        for unit in relation.units:
            host = relation.data[unit].get("hostname")
            port = relation.data[unit].get("port")
            if host and port:
                return sentry.RedisInfo(host=host, port=int(port))
        return None

    def _missing(self) -> list[str]:
        missing = []
        if self._postgres() is None:
            missing.append("database")
        if self._kafka() is None:
            missing.append("kafka")
        if self._redis() is None:
            missing.append("redis")
        if self.snuba.url is None:
            missing.append("snuba")
        return missing

    # -- secret-key -----------------------------------------------------------

    def _secret_key(self) -> str | None:
        """Return the shared Sentry secret key, generating it once on the leader."""
        peers = self.model.get_relation(PEER_RELATION)
        if peers is None:
            return None
        secret_id = peers.data[self.app].get("secret-key-id")
        if secret_id:
            return self.model.get_secret(id=secret_id).get_content(refresh=True)["secret-key"]
        if not self.unit.is_leader():
            return None
        key = secrets.token_hex(32)
        secret = self.app.add_secret({"secret-key": key}, label=SECRET_LABEL)
        peers.data[self.app]["secret-key-id"] = secret.id  # type: ignore[assignment]
        return key

    # -- reconcile ------------------------------------------------------------

    def _reconcile(self, _: ops.EventBase) -> None:
        # Open the web port so the `<app>.<model>.svc` ClusterIP service routes
        # to it (a k8s Service only forwards ports the charm opens); Relay and
        # ingress both connect to web:9000. The taskbroker (50051) and
        # symbolicator (3021) ports stay closed — they are reached over
        # localhost within the pod only.
        self.unit.set_ports(sentry.WEB_PORT)
        if not self.sentry_container.can_connect():
            return
        postgres = self._postgres()
        kafka = self._kafka()
        redis = self._redis()
        snuba_url = self.snuba.url
        secret_key = self._secret_key()
        if not (postgres and kafka and redis and snuba_url and secret_key):
            self.sentry_container.add_layer("sentry", {"services": {}}, combine=True)
            return

        self._push_sentry_config(postgres, kafka, redis)
        self._configure_taskbroker(kafka)
        self._configure_symbolicator()

        if self.unit.is_leader():
            self._migrate(postgres, kafka, redis, snuba_url, secret_key)

        self.sentry_container.add_layer(
            "sentry", self._sentry_layer(snuba_url, secret_key), combine=True
        )
        self.sentry_container.replan()

        self._publish_endpoints()

    def _push_sentry_config(
        self, postgres: sentry.PostgresInfo, kafka: sentry.KafkaInfo, redis: sentry.RedisInfo
    ) -> None:
        feature_complete = bool(self.config["feature-complete"])
        url_prefix = self._public_url
        self.sentry_container.push(
            sentry.SENTRY_CONF_PY,
            sentry.render_sentry_conf(
                postgres=postgres,
                redis=redis,
                kafka=kafka,
                feature_complete=feature_complete,
                csrf_origins=[url_prefix],
                behind_tls=url_prefix.startswith("https"),
            ),
            make_dirs=True,
        )
        self.sentry_container.push(
            sentry.SENTRY_CONFIG_YML,
            sentry.render_config_yml(
                url_prefix=url_prefix,
                enable_symbolicator=bool(self.config["enable-symbolicator"]),
                mail=self._mail_config(),
            ),
            make_dirs=True,
        )

    def _configure_taskbroker(self, kafka: sentry.KafkaInfo) -> None:
        if not self.taskbroker_container.can_connect():
            return
        self.taskbroker_container.push(
            sentry.TASKBROKER_CONFIG_YML, sentry.render_taskbroker_config(), make_dirs=True
        )
        self.taskbroker_container.add_layer(
            "taskbroker", self._taskbroker_layer(kafka), combine=True
        )
        self.taskbroker_container.replan()

    def _configure_symbolicator(self) -> None:
        if not self.symbolicator_container.can_connect():
            return
        if not bool(self.config["enable-symbolicator"]):
            return
        self.symbolicator_container.push(
            sentry.SYMBOLICATOR_CONFIG_YML, sentry.render_symbolicator_config(), make_dirs=True
        )
        self.symbolicator_container.add_layer(
            "symbolicator", self._symbolicator_layer(), combine=True
        )
        self.symbolicator_container.replan()

    def _migrate(
        self,
        postgres: sentry.PostgresInfo,
        kafka: sentry.KafkaInfo,
        redis: sentry.RedisInfo,
        snuba_url: str,
        secret_key: str,
    ) -> None:
        env = sentry.sentry_environment(
            snuba_url=snuba_url,
            secret_key=secret_key,
            event_retention_days=int(self.config["event-retention-days"]),  # type: ignore[arg-type]
        )
        logger.info("Creating Sentry's Kafka topics")
        try:
            self.sentry_container.exec(
                sentry.create_topics_command(), environment=env, timeout=300
            ).wait_output()
        except ops.pebble.ExecError as exc:
            logger.warning("Kafka topic creation failed (will retry): %s", exc)
        logger.info("Running sentry upgrade (database migrations)")
        try:
            process = self.sentry_container.exec(
                sentry.upgrade_command(), environment=env, timeout=900
            )
            process.wait_output()
        except ops.pebble.ExecError as exc:
            logger.warning("sentry upgrade failed (will retry): %s", exc)

    # -- layers ---------------------------------------------------------------

    def _sentry_layer(self, snuba_url: str, secret_key: str) -> ops.pebble.LayerDict:
        env = sentry.sentry_environment(
            snuba_url=snuba_url,
            secret_key=secret_key,
            event_retention_days=int(self.config["event-retention-days"]),  # type: ignore[arg-type]
        )
        concurrency = int(self.config["taskworker-concurrency"])  # type: ignore[arg-type]
        feature_complete = bool(self.config["feature-complete"])
        services: dict[str, ops.pebble.ServiceDict] = {}
        for service in sentry.enabled_services(feature_complete=feature_complete):
            command = service.command
            if "{concurrency}" in command:
                command = command.format(concurrency=concurrency)
            services[service.name] = {
                "override": "replace",
                "summary": service.name,
                "command": command,
                "startup": "enabled",
                "environment": env,
                "after": [] if service.name == "web" else ["web"],
            }
        return {
            "summary": "Sentry",
            "description": "Sentry web, task workers and consumers",
            "services": services,
            "checks": {
                "web-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": f"http://localhost:{sentry.WEB_PORT}/_health/"},
                    "period": "10s",
                    "timeout": "5s",
                    "threshold": 3,
                }
            },
        }

    def _taskbroker_layer(self, kafka: sentry.KafkaInfo) -> ops.pebble.LayerDict:
        return {
            "summary": "taskbroker",
            "services": {
                "taskbroker": {
                    "override": "replace",
                    "summary": "taskbroker",
                    "command": f"/opt/taskbroker -c {sentry.TASKBROKER_CONFIG_YML}",
                    "startup": "enabled",
                    "environment": sentry.taskbroker_environment(kafka),
                }
            },
        }

    def _symbolicator_layer(self) -> ops.pebble.LayerDict:
        return {
            "summary": "symbolicator",
            "services": {
                "symbolicator": {
                    "override": "replace",
                    "summary": "symbolicator",
                    "command": f"/bin/symbolicator run -c {sentry.SYMBOLICATOR_CONFIG_YML}",
                    "startup": "enabled",
                }
            },
        }

    # -- endpoints ------------------------------------------------------------

    @property
    def _internal_web_url(self) -> str:
        return f"http://{self.app.name}.{self.model.name}.svc.cluster.local:{sentry.WEB_PORT}"

    @property
    def _public_url(self) -> str:
        return self.ingress.url or self._internal_web_url

    def _publish_endpoints(self) -> None:
        self.relay.publish(web_url=self._internal_web_url)

    def _mail_config(self) -> dict[str, str] | None:
        host = str(self.config["smtp-host"])
        if not host:
            return None
        return {
            "host": host,
            "port": str(self.config["smtp-port"]),
            "username": str(self.config["smtp-username"]),
            "password": str(self.config["smtp-password"]),
            "use_tls": str(self.config["smtp-use-tls"]),
            "from": str(self.config["mail-from"]),
        }

    # -- actions --------------------------------------------------------------

    def _on_create_admin(self, event: ops.ActionEvent) -> None:
        if not self.unit.is_leader():
            event.fail("Run this action on the leader unit.")
            return
        if not self.sentry_container.can_connect():
            event.fail("Sentry container is not ready.")
            return
        email = event.params["email"]
        password = event.params.get("password") or secrets.token_urlsafe(18)
        postgres = self._postgres()
        snuba_url = self.snuba.url
        secret_key = self._secret_key()
        if not (postgres and snuba_url and secret_key):
            event.fail("Sentry is not fully integrated yet.")
            return
        env = sentry.sentry_environment(
            snuba_url=snuba_url,
            secret_key=secret_key,
            event_retention_days=int(self.config["event-retention-days"]),  # type: ignore[arg-type]
        )
        try:
            self.sentry_container.exec(
                sentry.createuser_command(email=email, password=password),
                environment=env,
                timeout=120,
            ).wait_output()
        except ops.pebble.ExecError as exc:
            event.fail(f"Failed to create admin user: {exc}")
            return
        secret = self.app.add_secret(
            {"email": email, "password": password}, label=f"sentry-admin-{email}"
        )
        event.set_results({"email": email, "password-secret": secret.id})

    # -- sentry-dsn integration -----------------------------------------------

    def _relay_host(self) -> str | None:
        """Return the in-cluster host events are ingested at (the related Relay)."""
        relation = self.model.get_relation(RELAY_RELATION)
        if relation is None or relation.app is None:
            return None
        return f"{relation.app.name}.{self.model.name}.svc.cluster.local"

    def _on_dsn_requested(self, event: ops.RelationEvent) -> None:
        """Provision a project/key for a related app and publish its DSN."""
        if not self.unit.is_leader() or not self.sentry_container.can_connect():
            return
        # A DSN is only useful once Sentry is bootstrapped and a Relay (the event
        # ingest endpoint) is related; otherwise wait for a later event.
        snuba_url = self.snuba.url
        secret_key = self._secret_key()
        relay_host = self._relay_host()
        if not (snuba_url and secret_key and relay_host):
            return
        project = self.sentry_dsn.requested_project(event.relation)
        if not project:
            return
        platform = self.sentry_dsn.requested_platform(event.relation)
        environment = self.sentry_dsn.requested_environment(event.relation) or self.model.name

        env = sentry.sentry_environment(
            snuba_url=snuba_url,
            secret_key=secret_key,
            event_retention_days=int(self.config["event-retention-days"]),  # type: ignore[arg-type]
        )
        env["SENTRY_DSN_ORG"] = DSN_ORGANIZATION
        env["SENTRY_DSN_PROJECT"] = project
        if platform:
            env["SENTRY_DSN_PLATFORM"] = platform
        try:
            output, _ = self.sentry_container.exec(
                sentry.provision_project_command(), environment=env, timeout=120
            ).wait_output()
        except ops.pebble.ExecError as exc:
            logger.warning("Failed to provision Sentry project %r: %s", project, exc)
            return
        parsed = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        public_key = parsed.get("PUBLIC_KEY")
        project_id = parsed.get("PROJECT_ID")
        if not (public_key and project_id):
            logger.warning("Project provisioning returned no DSN for %r", project)
            return
        ingest_url = f"http://{relay_host}:{RELAY_PORT}"
        dsn = f"http://{public_key}@{relay_host}:{RELAY_PORT}/{project_id}"
        self.sentry_dsn.publish_dsn(
            event.relation,
            dsn=dsn,
            public_key=public_key,
            project_id=project_id,
            ingest_url=ingest_url,
            environment=environment,
        )

    # -- tracing --------------------------------------------------------------

    @property
    def _charm_tracing_endpoint(self) -> str | None:
        """The Tempo otlp_http endpoint for charm self-tracing, if available."""
        if self._charm_tracing.is_ready():
            return self._charm_tracing.get_endpoint("otlp_http")
        return None

    # -- status ---------------------------------------------------------------

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        if not self.sentry_container.can_connect():
            event.add_status(ops.MaintenanceStatus("waiting for Sentry container"))
            return
        missing = self._missing()
        if missing:
            event.add_status(ops.BlockedStatus(f"missing integration(s): {', '.join(missing)}"))
            return
        services = self.sentry_container.get_services()
        if "web" not in services or not services["web"].is_running():
            event.add_status(ops.MaintenanceStatus("starting Sentry"))
            return
        event.add_status(ops.ActiveStatus())


if __name__ == "__main__":  # pragma: nocover
    ops.main(SentryK8SCharm)
