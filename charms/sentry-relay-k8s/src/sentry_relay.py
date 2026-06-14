# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Workload-specific logic for Relay.

Relay is configured through a YAML file (``config.yml``) and a generated
keypair (``credentials.json``), both read from its config directory
(``/work/.relay``). This module owns the rendering of ``config.yml`` and the
Kafka SASL ``kafka_config`` list, with no charming concerns, so it can be
unit-tested in isolation.

The shape of ``config.yml`` is transcribed from self-hosted Sentry's ``relay``
config (tag 26.5.2): ``relay.mode: managed`` points Relay at the Sentry web
upstream, ``processing.enabled`` turns on the event-processing pipeline (which
needs Kafka and Redis), and ``health.max_memory_percent`` works around a known
Kubernetes memory-detection bug that otherwise fails Relay's health check.
"""

from __future__ import annotations

import yaml

PORT = 3000
# Relay emits statsd metrics; a statsd-exporter sidecar takes statsd over UDP and
# re-exposes it as Prometheus metrics for COS to scrape.
STATSD_UDP_PORT = 9125
STATSD_METRICS_PORT = 9102
CONFIG_DIR = "/work/.relay"
CONFIG_PATH = f"{CONFIG_DIR}/config.yml"
CREDENTIALS_PATH = f"{CONFIG_DIR}/credentials.json"

# Relay's liveness endpoint; Pebble polls it as a 'ready' check.
HEALTHCHECK_PATH = "/api/relay/healthcheck/live/"

# librdkafka security values; SCRAM-SHA-512 matches kafka-k8s's default mechanism.
SASL_SECURITY_PROTOCOL = "SASL_PLAINTEXT"
SASL_MECHANISM = "SCRAM-SHA-512"


def build_kafka_config(
    *,
    brokers: str,
    username: str = "",
    password: str = "",
) -> list[dict[str, str]]:
    """Build Relay's ``processing.kafka_config`` list.

    Relay passes these straight to librdkafka as ``{name, value}`` pairs, so the
    SASL/SCRAM credentials for a Canonical ``kafka-k8s`` cluster are appended
    here when present.
    """
    config: list[dict[str, str]] = [{"name": "bootstrap.servers", "value": brokers}]
    if username:
        config += [
            {"name": "security.protocol", "value": SASL_SECURITY_PROTOCOL},
            {"name": "sasl.mechanism", "value": SASL_MECHANISM},
            {"name": "sasl.username", "value": username},
            {"name": "sasl.password", "value": password},
        ]
    return config


def build_config(
    *,
    upstream: str,
    kafka_brokers: str,
    redis_host: str,
    redis_port: int,
    kafka_username: str = "",
    kafka_password: str = "",
    log_level: str = "info",
) -> str:
    """Render Relay's ``config.yml`` as a YAML string."""
    config = {
        "relay": {
            "mode": "managed",
            "upstream": upstream,
            "host": "0.0.0.0",
            "port": PORT,
        },
        "logging": {
            "level": log_level,
        },
        "processing": {
            "enabled": True,
            "kafka_config": build_kafka_config(
                brokers=kafka_brokers,
                username=kafka_username,
                password=kafka_password,
            ),
            "redis": f"redis://{redis_host}:{redis_port}",
        },
        "health": {
            # Works around a known Kubernetes memory-detection bug that
            # otherwise fails Relay's health check.
            "max_memory_percent": 1.0,
        },
        # Emit statsd to the local statsd-exporter sidecar, which re-exposes the
        # metrics for Prometheus.
        "metrics": {
            "statsd": f"localhost:{STATSD_UDP_PORT}",
        },
    }
    return yaml.safe_dump(config, sort_keys=False)


def statsd_exporter_command() -> str:
    """Pebble command for the statsd-exporter sidecar (statsd UDP -> Prometheus)."""
    return (
        f"/bin/statsd_exporter --statsd.listen-udp=:{STATSD_UDP_PORT} "
        f"--web.listen-address=:{STATSD_METRICS_PORT}"
    )


def run_command() -> str:
    """Return the Pebble command that runs Relay (the image puts ``relay`` on PATH)."""
    return f"relay run --config {CONFIG_DIR}"


def credentials_generate_command() -> list[str]:
    """Return the one-shot command that generates Relay's keypair as JSON on stdout."""
    return ["relay", "credentials", "generate", "--stdout"]
