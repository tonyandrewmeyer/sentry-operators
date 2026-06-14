# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""Unit tests for the charmlibs.interfaces.sentry_dsn library.

The provider and requirer are exercised through tiny in-test charms, driven
with ``ops.testing``.
"""

import ops
from ops import testing

from charmlibs.interfaces.sentry_dsn import SentryDsnProvider, SentryDsnRequirer

PROVIDER_META = {
    "name": "sentry",
    "provides": {"sentry-dsn": {"interface": "sentry_dsn"}},
}
REQUIRER_META = {
    "name": "app",
    "requires": {"sentry-dsn": {"interface": "sentry_dsn"}},
}

PUBLISHED = {
    "dsn": "http://key@relay:3000/1",
    "public-key": "key",
    "project-id": "1",
    "ingest-url": "http://relay:3000",
    "environment": "demo",
}


class _ProviderCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.dsn = SentryDsnProvider(self)
        self.seen_request: tuple[str | None, str | None, str | None] | None = None
        framework.observe(self.dsn.on.dsn_requested, self._on_requested)

    def _on_requested(self, event: ops.RelationEvent) -> None:
        self.seen_request = (
            self.dsn.requested_project(event.relation),
            self.dsn.requested_platform(event.relation),
            self.dsn.requested_environment(event.relation),
        )
        self.dsn.publish_dsn(
            event.relation,
            dsn=PUBLISHED["dsn"],
            public_key=PUBLISHED["public-key"],
            project_id=PUBLISHED["project-id"],
            ingest_url=PUBLISHED["ingest-url"],
            environment=PUBLISHED["environment"],
        )


class _RequirerCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.sentry = SentryDsnRequirer(
            self, project_name="my-project", platform="python", environment="demo"
        )
        self.changes = 0
        self.gone = 0
        framework.observe(self.sentry.on.dsn_changed, self._on_changed)
        framework.observe(self.sentry.on.gone, self._on_gone)

    def _on_changed(self, _: ops.EventBase) -> None:
        self.changes += 1

    def _on_gone(self, _: ops.EventBase) -> None:
        self.gone += 1


def test_requirer_publishes_its_request():
    ctx = testing.Context(_RequirerCharm, meta=REQUIRER_META)
    relation = testing.Relation("sentry-dsn", remote_app_name="sentry")
    state = ctx.run(
        ctx.on.relation_joined(relation),
        testing.State(relations={relation}, leader=True),
    )
    data = state.get_relation(relation.id).local_app_data
    assert data["project-name"] == "my-project"
    assert data["platform"] == "python"
    assert data["environment"] == "demo"


def test_provider_reads_request_and_publishes_dsn():
    ctx = testing.Context(_ProviderCharm, meta=PROVIDER_META)
    relation = testing.Relation(
        "sentry-dsn",
        remote_app_name="app",
        remote_app_data={"project-name": "my-project", "platform": "python"},
    )
    with ctx(
        ctx.on.relation_changed(relation),
        testing.State(relations={relation}, leader=True),
    ) as manager:
        state = manager.run()
        assert manager.charm.seen_request == ("my-project", "python", None)
    data = state.get_relation(relation.id).local_app_data
    assert data == PUBLISHED


def test_provider_defaults_project_to_remote_app_name():
    ctx = testing.Context(_ProviderCharm, meta=PROVIDER_META)
    relation = testing.Relation("sentry-dsn", remote_app_name="app")
    with ctx(
        ctx.on.relation_changed(relation),
        testing.State(relations={relation}, leader=True),
    ) as manager:
        manager.run()
        assert manager.charm.seen_request[0] == "app"


def test_provider_does_not_publish_when_not_leader():
    ctx = testing.Context(_ProviderCharm, meta=PROVIDER_META)
    relation = testing.Relation("sentry-dsn", remote_app_name="app")
    state = ctx.run(
        ctx.on.relation_changed(relation),
        testing.State(relations={relation}, leader=False),
    )
    assert state.get_relation(relation.id).local_app_data == {}


def test_requirer_reads_dsn_and_emits_changed():
    ctx = testing.Context(_RequirerCharm, meta=REQUIRER_META)
    relation = testing.Relation("sentry-dsn", remote_app_name="sentry", remote_app_data=PUBLISHED)
    with ctx(
        ctx.on.relation_changed(relation),
        testing.State(relations={relation}, leader=True),
    ) as manager:
        manager.run()
        assert manager.charm.sentry.dsn == PUBLISHED["dsn"]
        assert manager.charm.sentry.public_key == PUBLISHED["public-key"]
        assert manager.charm.sentry.project_id == PUBLISHED["project-id"]
        assert manager.charm.sentry.ingest_url == PUBLISHED["ingest-url"]
        assert manager.charm.sentry.environment == PUBLISHED["environment"]
        assert manager.charm.changes == 1


def test_requirer_dsn_is_none_without_data():
    ctx = testing.Context(_RequirerCharm, meta=REQUIRER_META)
    relation = testing.Relation("sentry-dsn", remote_app_name="sentry")
    with ctx(
        ctx.on.relation_changed(relation),
        testing.State(relations={relation}, leader=True),
    ) as manager:
        manager.run()
        assert manager.charm.sentry.dsn is None
        assert manager.charm.changes == 0


def test_requirer_emits_gone_on_broken():
    ctx = testing.Context(_RequirerCharm, meta=REQUIRER_META)
    relation = testing.Relation("sentry-dsn", remote_app_name="sentry", remote_app_data=PUBLISHED)
    with ctx(
        ctx.on.relation_broken(relation),
        testing.State(relations={relation}, leader=True),
    ) as manager:
        manager.run()
        assert manager.charm.gone == 1
