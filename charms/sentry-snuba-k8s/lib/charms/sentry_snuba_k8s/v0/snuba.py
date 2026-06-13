"""Library for the ``sentry_snuba`` relation interface.

This library implements **both sides** of the ``sentry_snuba`` interface, which
the Snuba charm (the *provider*) uses to hand the Sentry charm (the *requirer*)
the URL of Snuba's HTTP query API.

It is a small, internal interface for the ``sentry-operators`` charm set.

## Getting started

### Provider (the Snuba charm)

```python
from charms.sentry_snuba_k8s.v0.snuba import SnubaProvider

self.snuba = SnubaProvider(self)
self.snuba.publish(url="http://sentry-snuba-k8s.mymodel.svc.cluster.local:1218")
```

### Requirer (the Sentry charm)

```python
from charms.sentry_snuba_k8s.v0.snuba import SnubaRequirer

self.snuba = SnubaRequirer(self)
framework.observe(self.snuba.on.ready, self._reconcile)
url = self.snuba.url  # None until the provider publishes it
```
"""

from __future__ import annotations

import logging

import ops

# The unique Charmhub library identifier, never change it.
LIBID = "0s0n0u0b0a0000000000000000snuba0"
LIBAPI = 0
LIBPATCH = 1

DEFAULT_RELATION_NAME = "snuba"

logger = logging.getLogger(__name__)


class SnubaProvider(ops.Object):
    """The provider (server) side of the ``sentry_snuba`` interface."""

    def __init__(self, charm: ops.CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    def publish(self, *, url: str) -> None:
        """Publish the Snuba API URL to related requirers (leader only)."""
        if not self._charm.unit.is_leader():
            return
        for relation in self.model.relations[self._relation_name]:
            relation.data[self._charm.app]["url"] = url


class _SnubaReadyEvent(ops.EventBase):
    """Emitted when the Snuba API URL becomes available."""


class _SnubaGoneEvent(ops.EventBase):
    """Emitted when the Snuba relation is removed."""


class SnubaRequirerEvents(ops.ObjectEvents):
    """Events emitted by :class:`SnubaRequirer`."""

    ready = ops.EventSource(_SnubaReadyEvent)
    gone = ops.EventSource(_SnubaGoneEvent)


class SnubaRequirer(ops.Object):
    """The requirer (client) side of the ``sentry_snuba`` interface."""

    on = SnubaRequirerEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: ops.CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_changed)
        self.framework.observe(charm.on[relation_name].relation_broken, self._on_broken)

    def _on_changed(self, event: ops.RelationChangedEvent) -> None:
        if self.url is not None:
            self.on.ready.emit()

    def _on_broken(self, event: ops.RelationBrokenEvent) -> None:
        self.on.gone.emit()

    @property
    def url(self) -> str | None:
        """The Snuba HTTP API URL, or ``None`` if not yet available."""
        relation = self.model.get_relation(self._relation_name)
        if relation is None or relation.app is None:
            return None
        return relation.data[relation.app].get("url") or None
