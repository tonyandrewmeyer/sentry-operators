# Copyright 2026 Tony Meyer
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The charmlibs.interfaces.sentry_dsn package.

Integrate any charm with self-hosted Sentry and receive a ready-to-use **DSN**
over relation data, so the application (and the charm itself) can report errors
to Sentry without anyone creating a project or copying a DSN by hand. It is the
*Juju way* of wiring an application to Sentry.

The Sentry charm is the **provider**: when a requirer relates, the provider
creates (idempotently) a Sentry project and key for it and publishes the DSN.
A requirer optionally asks for a particular project name, platform and
environment.

## Requirer (your application charm)

Declare a ``requires`` endpoint with the ``sentry_dsn`` interface in
``charmcraft.yaml`` and depend on this package, then:

```python
from charmlibs.interfaces.sentry_dsn import SentryDsnRequirer

self.sentry = SentryDsnRequirer(
    self, relation_name="sentry-dsn", project_name=self.app.name, platform="python"
)
self.framework.observe(self.sentry.on.dsn_changed, self._reconcile)
self.framework.observe(self.sentry.on.gone, self._reconcile)
...
dsn = self.sentry.dsn  # None until Sentry publishes it; set it on your workload
```

## Provider (the Sentry charm), endpoint ``sentry-dsn``

```python
from charmlibs.interfaces.sentry_dsn import SentryDsnProvider

self.dsn = SentryDsnProvider(self, relation_name="sentry-dsn")
self.framework.observe(self.dsn.on.dsn_requested, self._on_dsn_requested)
...
# in the handler, create the project/key and publish:
self.dsn.publish_dsn(event.relation, dsn=dsn, public_key=key,
                     project_id=pid, ingest_url=url, environment=env)
```
"""

from __future__ import annotations

import logging

import ops

from ._version import __version__ as __version__

__all__ = [
    "SentryDsnProvider",
    "SentryDsnRequirer",
]

logger = logging.getLogger(__name__)

# Relation-data keys. Requirer -> provider: the request. Provider -> requirer:
# the resulting DSN and its parts.
_REQ_PROJECT = "project-name"
_REQ_PLATFORM = "platform"
_REQ_ENVIRONMENT = "environment"
_RESP_DSN = "dsn"
_RESP_PUBLIC_KEY = "public-key"
_RESP_PROJECT_ID = "project-id"
_RESP_INGEST_URL = "ingest-url"
_RESP_ENVIRONMENT = "environment"


class _DsnRequestedEvent(ops.RelationEvent):
    """Emitted on the provider when a requirer needs (or re-requests) a DSN."""


class SentryDsnProviderEvents(ops.ObjectEvents):
    """Events emitted by :class:`SentryDsnProvider`."""

    dsn_requested = ops.EventSource(_DsnRequestedEvent)


class SentryDsnProvider(ops.Object):
    """The provider (Sentry) side of the ``sentry_dsn`` interface.

    Emits :attr:`on.dsn_requested` when a requirer joins or updates its request;
    the charm responds by provisioning a project/key and calling
    :meth:`publish_dsn`.
    """

    on = SentryDsnProviderEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: ops.CharmBase, relation_name: str = "sentry-dsn"):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_joined, self._on_relation_changed)
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_relation_changed)

    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        self.on.dsn_requested.emit(event.relation, app=event.app, unit=event.unit)

    def requested_project(self, relation: ops.Relation) -> str | None:
        """Return the project name the requirer asked for (else its app name)."""
        if relation.app is None:
            return None
        return relation.data[relation.app].get(_REQ_PROJECT) or relation.app.name

    def requested_platform(self, relation: ops.Relation) -> str | None:
        """Return the platform the requirer declared, e.g. ``python`` (or ``None``)."""
        if relation.app is None:
            return None
        return relation.data[relation.app].get(_REQ_PLATFORM) or None

    def requested_environment(self, relation: ops.Relation) -> str | None:
        """Return the environment the requirer asked for (or ``None``)."""
        if relation.app is None:
            return None
        return relation.data[relation.app].get(_REQ_ENVIRONMENT) or None

    def publish_dsn(
        self,
        relation: ops.Relation,
        *,
        dsn: str,
        public_key: str,
        project_id: str,
        ingest_url: str,
        environment: str | None = None,
    ) -> None:
        """Publish a DSN (and its parts) to one requirer (leader only)."""
        if not self._charm.unit.is_leader():
            return
        data = relation.data[self._charm.app]
        data[_RESP_DSN] = dsn
        data[_RESP_PUBLIC_KEY] = public_key
        data[_RESP_PROJECT_ID] = project_id
        data[_RESP_INGEST_URL] = ingest_url
        if environment:
            data[_RESP_ENVIRONMENT] = environment


class _DsnChangedEvent(ops.EventBase):
    """Emitted on the requirer when the DSN becomes available or changes."""


class _DsnGoneEvent(ops.EventBase):
    """Emitted on the requirer when the Sentry relation is removed."""


class SentryDsnRequirerEvents(ops.ObjectEvents):
    """Events emitted by :class:`SentryDsnRequirer`."""

    dsn_changed = ops.EventSource(_DsnChangedEvent)
    gone = ops.EventSource(_DsnGoneEvent)


class SentryDsnRequirer(ops.Object):
    """The requirer (your application) side of the ``sentry_dsn`` interface.

    Pass the project name/platform/environment you want; they are sent to the
    Sentry charm, which provisions a project and publishes a :attr:`dsn`.
    """

    on = SentryDsnRequirerEvents()  # type: ignore[reportAssignmentType]

    def __init__(
        self,
        charm: ops.CharmBase,
        relation_name: str = "sentry-dsn",
        *,
        project_name: str | None = None,
        platform: str | None = None,
        environment: str | None = None,
    ):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._project_name = project_name
        self._platform = platform
        self._environment = environment
        self.framework.observe(charm.on[relation_name].relation_joined, self._on_relation_created)
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_changed)
        self.framework.observe(charm.on[relation_name].relation_broken, self._on_broken)

    def _on_relation_created(self, event: ops.RelationJoinedEvent) -> None:
        self._publish_request(event.relation)

    def _on_changed(self, event: ops.RelationChangedEvent) -> None:
        # Re-send the request (e.g. after a leadership change) and surface the DSN.
        self._publish_request(event.relation)
        if self.dsn is not None:
            self.on.dsn_changed.emit()

    def _on_broken(self, event: ops.RelationBrokenEvent) -> None:
        self.on.gone.emit()

    def _publish_request(self, relation: ops.Relation) -> None:
        """Write the requested project/platform/environment (leader only)."""
        if not self._charm.unit.is_leader():
            return
        data = relation.data[self._charm.app]
        data[_REQ_PROJECT] = self._project_name or self._charm.app.name
        if self._platform:
            data[_REQ_PLATFORM] = self._platform
        if self._environment:
            data[_REQ_ENVIRONMENT] = self._environment

    def _provider_data(self) -> ops.RelationDataContent | None:
        relation = self.model.get_relation(self._relation_name)
        if relation is None or relation.app is None:
            return None
        return relation.data[relation.app]

    @property
    def dsn(self) -> str | None:
        """The Sentry DSN to point an SDK at, or ``None`` if not yet available."""
        data = self._provider_data()
        return data.get(_RESP_DSN) if data else None

    @property
    def public_key(self) -> str | None:
        """The DSN public key (useful to build a DSN for a browser SDK)."""
        data = self._provider_data()
        return data.get(_RESP_PUBLIC_KEY) if data else None

    @property
    def project_id(self) -> str | None:
        """The numeric Sentry project id."""
        data = self._provider_data()
        return data.get(_RESP_PROJECT_ID) if data else None

    @property
    def ingest_url(self) -> str | None:
        """The base URL events are ingested at (the Relay endpoint)."""
        data = self._provider_data()
        return data.get(_RESP_INGEST_URL) if data else None

    @property
    def environment(self) -> str | None:
        """The environment name, if the provider supplied one."""
        data = self._provider_data()
        return data.get(_RESP_ENVIRONMENT) if data else None
