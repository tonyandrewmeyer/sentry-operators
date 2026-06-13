# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the Relay workload module."""

import yaml

import sentry_relay


def _render(**kwargs):
    defaults = {
        "upstream": "http://sentry-k8s.m.svc.cluster.local:9000/",
        "kafka_brokers": "kafka:9092",
        "redis_host": "redis",
        "redis_port": 6379,
    }
    defaults.update(kwargs)
    return yaml.safe_load(sentry_relay.build_config(**defaults))


def test_config_upstream_and_basics():
    config = _render()
    assert config["relay"]["mode"] == "managed"
    assert config["relay"]["upstream"] == "http://sentry-k8s.m.svc.cluster.local:9000/"
    assert config["relay"]["host"] == "0.0.0.0"
    assert config["relay"]["port"] == 3000


def test_config_processing_enabled():
    config = _render()
    assert config["processing"]["enabled"] is True


def test_config_redis_url():
    config = _render(redis_host="r.host", redis_port=6380)
    assert config["processing"]["redis"] == "redis://r.host:6380"


def test_config_health_max_memory_percent():
    config = _render()
    assert config["health"]["max_memory_percent"] == 1.0


def test_config_log_level():
    config = _render(log_level="debug")
    assert config["logging"]["level"] == "debug"


def _kafka_pairs(config):
    return {entry["name"]: entry["value"] for entry in config["processing"]["kafka_config"]}


def test_kafka_config_bootstrap_servers():
    config = _render(kafka_brokers="b1:9092,b2:9092")
    pairs = _kafka_pairs(config)
    assert pairs["bootstrap.servers"] == "b1:9092,b2:9092"


def test_kafka_config_has_sasl_when_credentials_given():
    config = _render(kafka_username="relay-user", kafka_password="p@ss")
    pairs = _kafka_pairs(config)
    assert pairs["security.protocol"] == "SASL_PLAINTEXT"
    assert pairs["sasl.mechanism"] == "SCRAM-SHA-512"
    assert pairs["sasl.username"] == "relay-user"
    assert pairs["sasl.password"] == "p@ss"


def test_kafka_config_omits_sasl_without_credentials():
    config = _render()
    pairs = _kafka_pairs(config)
    assert "security.protocol" not in pairs
    assert "sasl.username" not in pairs


def test_build_kafka_config_directly():
    config = sentry_relay.build_kafka_config(brokers="k:9092")
    assert config == [{"name": "bootstrap.servers", "value": "k:9092"}]


def test_run_command():
    assert sentry_relay.run_command() == "relay run --config /work/.relay"


def test_credentials_generate_command():
    assert sentry_relay.credentials_generate_command() == [
        "relay",
        "credentials",
        "generate",
        "--stdout",
    ]
