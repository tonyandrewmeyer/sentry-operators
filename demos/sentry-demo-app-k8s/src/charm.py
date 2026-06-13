#!/usr/bin/env python3
# Copyright 2026 Tony Meyer
# See LICENSE file for licensing details.

"""A tiny demo web app that reports errors to Sentry via the sentry_dsn relation.

This is the *requirer* side of the ``sentry_dsn`` interface. It asks the Sentry
charm for a DSN and, when it arrives, configures both its Python backend and its
JavaScript frontend (and the charm itself) to report errors to Sentry.
"""

from __future__ import annotations

import logging
import pathlib

import ops
from charmlibs.interfaces.sentry_dsn import SentryDsnRequirer

logger = logging.getLogger(__name__)

CONTAINER = "app"
PORT = 8080
APP_DIR = "/app"


class SentryDemoAppCharm(ops.CharmBase):
    """A web app that integrates with Sentry over the sentry_dsn interface."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container(CONTAINER)
        # Ask Sentry for a DSN; the project is named after this application.
        self.sentry = SentryDsnRequirer(
            self, relation_name="sentry-dsn", project_name=self.app.name, platform="python"
        )
        for event in (
            self.on[CONTAINER].pebble_ready,
            self.on.config_changed,
            self.sentry.on.dsn_changed,
            self.sentry.on.gone,
        ):
            framework.observe(event, self._reconcile)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

    def _reconcile(self, _: ops.EventBase) -> None:
        if not self.container.can_connect():
            return
        self.unit.set_ports(PORT)
        self._push_app()
        self.container.add_layer("app", self._layer(), combine=True)
        self.container.replan()

    def _push_app(self) -> None:
        """Push the backend and frontend sources into the workload container."""
        source = pathlib.Path(__file__).parent / "app"
        for name in ("backend.py", "index.html"):
            self.container.push(f"{APP_DIR}/{name}", (source / name).read_text(), make_dirs=True)

    def _layer(self) -> ops.pebble.LayerDict:
        # Everything the backend and the frontend need to talk to Sentry comes
        # from the relation; with no DSN yet the app still runs (errors are just
        # not reported) so the page is reachable.
        env = {
            "SENTRY_DSN": self.sentry.dsn or "",
            "SENTRY_PUBLIC_KEY": self.sentry.public_key or "",
            "SENTRY_INGEST_URL": self.sentry.ingest_url or "",
            "SENTRY_PROJECT_ID": self.sentry.project_id or "",
            "SENTRY_ENVIRONMENT": self.sentry.environment or "",
            "APP_PORT": str(PORT),
        }
        return {
            "summary": "Sentry demo app",
            "description": "A Flask backend + browser frontend wired to Sentry.",
            "services": {
                "app": {
                    "override": "replace",
                    "summary": "demo web app",
                    # The slim image has no Flask/SDK; install them on start.
                    "command": (
                        "bash -c 'pip install --quiet --root-user-action=ignore "
                        '"sentry-sdk[flask]" flask && python '
                        f"{APP_DIR}/backend.py'"
                    ),
                    "startup": "enabled",
                    "environment": env,
                }
            },
        }

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        if not self.container.can_connect():
            event.add_status(ops.MaintenanceStatus("waiting for app container"))
            return
        if self.sentry.dsn is None:
            event.add_status(ops.BlockedStatus("waiting for sentry-dsn integration"))
            return
        event.add_status(ops.ActiveStatus(f"reporting to Sentry project {self.app.name}"))


if __name__ == "__main__":  # pragma: nocover
    ops.main(SentryDemoAppCharm)
