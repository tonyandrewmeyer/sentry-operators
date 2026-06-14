"""Library for the ``sentry_relay`` relation interface.

This library implements **both sides** of the ``sentry_relay`` interface, which
the Sentry charm (the *provider*) uses to hand the Relay charm (the *requirer*)
the internal URL of Sentry's web (upstream) service. Relay is a managed event
intake proxy and forwards processed events to that upstream.

It is a small, internal interface for the ``sentry-operators`` charm set.

Note that the endpoint names differ between the two sides: the provider (the
Sentry charm) exposes an endpoint named ``sentry-relay``, while the requirer
(the Relay charm) consumes it on an endpoint named ``sentry``. Both classes take
a ``relation_name`` argument so each side can pass the name it uses.

## Getting started

### Provider (the Sentry charm)

```python
from charms.sentry_k8s.v0.sentry_relay import SentryRelayProvider

self.sentry_relay = SentryRelayProvider(self)
self.sentry_relay.publish(web_url="http://sentry-k8s.mymodel.svc.cluster.local:9000/")
```

### Requirer (the Relay charm)

```python
from charms.sentry_k8s.v0.sentry_relay import SentryRelayRequirer

self.sentry = SentryRelayRequirer(self)
framework.observe(self.sentry.on.ready, self._reconcile)
web_url = self.sentry.web_url  # None until the provider publishes it
```
"""

from __future__ import annotations

import logging

import ops

# The unique Charmhub library identifier, never change it.
LIBID = "c5f3e2d07a2c6d3ebf40516273849506"
LIBAPI = 0
LIBPATCH = 1

PROVIDER_RELATION_NAME = "sentry-relay"
REQUIRER_RELATION_NAME = "sentry"

logger = logging.getLogger(__name__)


class SentryRelayProvider(ops.Object):
    """The provider (server) side of the ``sentry_relay`` interface."""

    def __init__(self, charm: ops.CharmBase, relation_name: str = PROVIDER_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    def publish(self, *, web_url: str) -> None:
        """Publish the Sentry web (upstream) URL to related requirers (leader only)."""
        if not self._charm.unit.is_leader():
            return
        for relation in self.model.relations[self._relation_name]:
            relation.data[self._charm.app]["web-url"] = web_url


class _SentryRelayReadyEvent(ops.EventBase):
    """Emitted when the Sentry web URL becomes available."""


class _SentryRelayGoneEvent(ops.EventBase):
    """Emitted when the Sentry relation is removed."""


class SentryRelayRequirerEvents(ops.ObjectEvents):
    """Events emitted by :class:`SentryRelayRequirer`."""

    ready = ops.EventSource(_SentryRelayReadyEvent)
    gone = ops.EventSource(_SentryRelayGoneEvent)


class SentryRelayRequirer(ops.Object):
    """The requirer (client) side of the ``sentry_relay`` interface."""

    on = SentryRelayRequirerEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: ops.CharmBase, relation_name: str = REQUIRER_RELATION_NAME):
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
        """The Sentry web (upstream) URL, or ``None`` if not yet available."""
        relation = self.model.get_relation(self._relation_name)
        if relation is None or relation.app is None:
            return None
        return relation.data[relation.app].get("web-url") or None
