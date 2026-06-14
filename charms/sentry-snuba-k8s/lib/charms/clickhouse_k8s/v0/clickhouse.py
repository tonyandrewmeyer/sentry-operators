"""Library for the ``sentry_clickhouse`` relation interface.

This library implements **both sides** of the ``sentry_clickhouse`` interface,
which a ClickHouse charm (the *provider*) uses to hand a consumer (the
*requirer*, e.g. Snuba) the connection details for a single-node ClickHouse
server.

It is a small, self-contained interface used internally by the
``sentry-operators`` charm set; it is not a general-purpose ClickHouse client.

## Getting started

### Provider (the ClickHouse charm)

```python
from charms.clickhouse_k8s.v0.clickhouse import ClickHouseProvider

class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.clickhouse = ClickHouseProvider(self)
        # When the workload is ready, publish the connection details:
        self.clickhouse.publish(
            host="clickhouse-k8s.mymodel.svc.cluster.local",
            http_port=8123,
            native_port=9000,
            username="default",
        )
```

### Requirer (e.g. the Snuba charm)

```python
from charms.clickhouse_k8s.v0.clickhouse import ClickHouseRequirer

class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.clickhouse = ClickHouseRequirer(self)
        framework.observe(self.clickhouse.on.ready, self._on_clickhouse_ready)
        framework.observe(self.clickhouse.on.gone, self._on_clickhouse_gone)

    def _on_clickhouse_ready(self, event):
        info = self.clickhouse.get_connection()
        if info:
            ...  # configure the workload with info.host, info.http_port, ...
```
"""

from __future__ import annotations

import dataclasses
import logging

import ops

# The unique Charmhub library identifier, never change it.
# (Placeholder for an internal, not-yet-published library.)
LIBID = "a3f1c0de5e0a4b1c9d2e3f4051627384"

# Increment this major API version when introducing breaking changes.
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib`.
LIBPATCH = 1

DEFAULT_RELATION_NAME = "clickhouse"

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ClickHouseConnection:
    """Connection details for a ClickHouse server."""

    host: str
    """Hostname (typically the Kubernetes service FQDN) of the server."""
    http_port: int
    """The HTTP interface port (default 8123)."""
    native_port: int
    """The native TCP protocol port (default 9000)."""
    username: str
    """The username to authenticate with."""
    password: str = ""
    """The password to authenticate with (empty for a passwordless default user)."""


class ClickHouseProvider(ops.Object):
    """The provider (server) side of the ``sentry_clickhouse`` interface."""

    def __init__(self, charm: ops.CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    def publish(
        self,
        *,
        host: str,
        http_port: int = 8123,
        native_port: int = 9000,
        username: str = "default",
        password: str = "",
    ) -> None:
        """Publish the connection details to every related requirer.

        Only the leader unit writes to the application databag. Calling this on a
        non-leader unit is a no-op.
        """
        if not self._charm.unit.is_leader():
            return
        for relation in self.model.relations[self._relation_name]:
            relation.data[self._charm.app].update(
                {
                    "host": host,
                    "http-port": str(http_port),
                    "native-port": str(native_port),
                    "username": username,
                    "password": password,
                }
            )


class _ClickHouseReadyEvent(ops.EventBase):
    """Emitted when ClickHouse connection details become available."""


class _ClickHouseGoneEvent(ops.EventBase):
    """Emitted when the ClickHouse relation is removed."""


class ClickHouseRequirerEvents(ops.ObjectEvents):
    """Events emitted by :class:`ClickHouseRequirer`."""

    ready = ops.EventSource(_ClickHouseReadyEvent)
    gone = ops.EventSource(_ClickHouseGoneEvent)


class ClickHouseRequirer(ops.Object):
    """The requirer (client) side of the ``sentry_clickhouse`` interface."""

    on = ClickHouseRequirerEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: ops.CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        framework = self.framework
        framework.observe(charm.on[relation_name].relation_changed, self._on_changed)
        framework.observe(charm.on[relation_name].relation_broken, self._on_broken)

    def _on_changed(self, event: ops.RelationChangedEvent) -> None:
        if self.get_connection() is not None:
            self.on.ready.emit()

    def _on_broken(self, event: ops.RelationBrokenEvent) -> None:
        self.on.gone.emit()

    def get_connection(self) -> ClickHouseConnection | None:
        """Return the ClickHouse connection details, or ``None`` if not ready."""
        relation = self.model.get_relation(self._relation_name)
        if relation is None or relation.app is None:
            return None
        data = relation.data[relation.app]
        host = data.get("host")
        if not host:
            return None
        try:
            return ClickHouseConnection(
                host=host,
                http_port=int(data.get("http-port", "8123")),
                native_port=int(data.get("native-port", "9000")),
                username=data.get("username", "default"),
                password=data.get("password", ""),
            )
        except ValueError:
            logger.warning("Malformed clickhouse relation data: %r", dict(data))
            return None
