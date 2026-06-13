# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Workload-specific logic for ClickHouse.

This module renders ClickHouse's configuration and talks to its HTTP interface.
It deliberately has no charming concerns so it can be unit-tested on its own.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

HTTP_PORT = 8123
NATIVE_PORT = 9000

# Where the charm pushes its drop-in configuration inside the workload container.
SERVER_CONFIG_PATH = "/etc/clickhouse-server/config.d/sentry.xml"
USERS_CONFIG_PATH = "/etc/clickhouse-server/users.d/sentry.xml"

# Valid ClickHouse logger levels, smallest to largest.
LOG_LEVELS = ("none", "fatal", "error", "warning", "information", "debug", "trace")


def render_server_config(*, max_memory_ratio: float, log_level: str) -> str:
    """Render the server drop-in config.

    Mirrors self-hosted Sentry's ``clickhouse/config.xml``: listen on all
    interfaces (so Snuba can reach it across pods), cap memory relative to the
    unit's RAM, and disable the noisy internal system-log tables.
    """
    if log_level not in LOG_LEVELS:
        log_level = "warning"
    disabled_logs = (
        "query_log",
        "query_thread_log",
        "query_views_log",
        "text_log",
        "trace_log",
        "metric_log",
        "asynchronous_metric_log",
        "session_log",
        "part_log",
        "processors_profile_log",
        "error_log",
        "latency_log",
    )
    removed = "\n".join(f'    <{name} remove="remove"/>' for name in disabled_logs)
    return f"""<?xml version="1.0"?>
<clickhouse>
    <listen_host>0.0.0.0</listen_host>
    <logger>
        <level>{log_level}</level>
        <console>true</console>
    </logger>
    <max_server_memory_usage_to_ram_ratio>{max_memory_ratio}</max_server_memory_usage_to_ram_ratio>
    <merge_tree>
        <enable_mixed_granularity_parts>1</enable_mixed_granularity_parts>
        <max_suspicious_broken_parts>100</max_suspicious_broken_parts>
        <allow_nullable_key>1</allow_nullable_key>
    </merge_tree>
{removed}
</clickhouse>
"""


def render_users_config() -> str:
    """Render the users drop-in config.

    Snuba's ``self_hosted`` settings connect as the ``default`` user with no
    password. The server is only reachable on the in-cluster pod network, so we
    keep that default and disable per-query logging in the default profile.
    """
    return """<?xml version="1.0"?>
<clickhouse>
    <profiles>
        <default>
            <log_queries>0</log_queries>
            <log_query_threads>0</log_query_threads>
        </default>
    </profiles>
    <users>
        <default>
            <password></password>
            <networks>
                <ip>::/0</ip>
            </networks>
            <profile>default</profile>
            <quota>default</quota>
            <access_management>1</access_management>
        </default>
    </users>
</clickhouse>
"""


def _query(sql: str, *, host: str = "127.0.0.1", timeout: float = 5.0) -> str | None:
    """Run a read-only SQL statement over the HTTP interface and return the body."""
    url = f"http://{host}:{HTTP_PORT}/?query={urllib.parse.quote(sql)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return response.read().decode().strip()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        logger.debug("ClickHouse query failed: %s", exc)
        return None


def get_version(host: str = "127.0.0.1") -> str | None:
    """Return the running ClickHouse server version, or ``None`` if unreachable."""
    return _query("SELECT version()", host=host)


def is_ready(host: str = "127.0.0.1") -> bool:
    """Return whether the server answers a trivial query."""
    return _query("SELECT 1", host=host) == "1"
