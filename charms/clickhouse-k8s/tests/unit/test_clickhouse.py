# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the ClickHouse workload module."""

import clickhouse


def test_server_config_contains_listen_and_memory():
    cfg = clickhouse.render_server_config(max_memory_ratio=0.3, log_level="warning")
    assert "<listen_host>0.0.0.0</listen_host>" in cfg
    assert "<max_server_memory_usage_to_ram_ratio>0.3" in cfg
    assert '<query_log remove="remove"/>' in cfg


def test_server_config_exposes_prometheus_metrics():
    cfg = clickhouse.render_server_config(max_memory_ratio=0.3, log_level="warning")
    assert "<prometheus>" in cfg
    assert "<endpoint>/metrics</endpoint>" in cfg
    assert f"<port>{clickhouse.METRICS_PORT}</port>" in cfg
    assert "<port>9363</port>" in cfg


def test_server_config_rejects_bad_log_level():
    cfg = clickhouse.render_server_config(max_memory_ratio=0.3, log_level="bogus")
    assert "<level>warning</level>" in cfg


def test_users_config_default_user_passwordless():
    cfg = clickhouse.render_users_config()
    assert "<default>" in cfg
    assert "<password></password>" in cfg


def test_is_ready_false_when_unreachable():
    # Nothing is listening on this port during unit tests.
    assert clickhouse.is_ready(host="127.0.0.1") is False
