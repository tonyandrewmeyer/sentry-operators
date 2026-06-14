"""Library for the ``sentry_relay`` relation interface.

This library implements **both sides** of the ``sentry_relay`` interface, which
the Sentry charm (the *provider*) uses to hand the Relay charm (the *requirer*)
the internal URL of Sentry's web service. Relay forwards ingested events to that
URL and registers with it.

It is a small, internal interface for the ``sentry-operators`` charm set.

## Getting started

### Provider (the Sentry charm), endpoint ``sentry-relay``

```python
from charms.sentry_k8s.v0.sentry_relay import SentryRelayProvider

self.relay = SentryRelayProvider(self, relation_name="sentry-relay")
self.relay.publish(web_url="http://sentry-k8s.mymodel.svc.cluster.local:9000/")
```

### Requirer (the Relay charm), endpoint ``sentry``

```python
from charms.sentry_k8s.v0.sentry_relay import SentryRelayRequirer

self.sentry = SentryRelayRequirer(self, relation_name="sentry")
framework.observe(self.sentry.on.ready, self._reconcile)
url = self.sentry.web_url  # None until the provider publishes it
```
"""

from __future__ import annotations

import logging

import ops

# The unique Charmhub library identifier, never change it.
LIBID = "c5f3e2d07a2c6d3ebf40516273849506"
LIBAPI = 0
LIBPATCH = 1

logger = logging.getLogger(__name__)


class SentryRelayProvider(ops.Object):
    """The provider (Sentry) side of the ``sentry_relay`` interface."""

    def __init__(self, charm: ops.CharmBase, relation_name: str = "sentry-relay"):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    def publish(self, *, web_url: str) -> None:
        """Publish the Sentry web URL to related requirers (leader only)."""
        if not self._charm.unit.is_leader():
            return
        for relation in self.model.relations[self._relation_name]:
            relation.data[self._charm.app]["web-url"] = web_url


class _RelayReadyEvent(ops.EventBase):
    """Emitted when the Sentry web URL becomes available."""


class _RelayGoneEvent(ops.EventBase):
    """Emitted when the Sentry relation is removed."""


class SentryRelayRequirerEvents(ops.ObjectEvents):
    """Events emitted by :class:`SentryRelayRequirer`."""

    ready = ops.EventSource(_RelayReadyEvent)
    gone = ops.EventSource(_RelayGoneEvent)


class SentryRelayRequirer(ops.Object):
    """The requirer (Relay) side of the ``sentry_relay`` interface."""

    on = SentryRelayRequirerEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: ops.CharmBase, relation_name: str = "sentry"):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_changed)
        self.framework.observe(charm.on[relation_name].relation_broken, self._on_broken)

    def _on_changed(self, event: ops.RelationChangedEvent) -> None:
        if self.web_url is not None:
            self.on.ready.emit()

    def _on_broken(self, event: ops.RelationBrokenEvent) -> None:
        self.on.gone.emit()

    @property
    def web_url(self) -> str | None:
        """The Sentry web internal URL, or ``None`` if not yet available."""
        relation = self.model.get_relation(self._relation_name)
        if relation is None or relation.app is None:
            return None
        return relation.data[relation.app].get("web-url") or None
