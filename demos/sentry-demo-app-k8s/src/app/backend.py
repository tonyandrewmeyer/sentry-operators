"""The demo application's Python backend.

A tiny Flask service instrumented with the Sentry Python SDK. The DSN and the
browser ingest details come entirely from the environment, which the charm sets
from the ``sentry_dsn`` relation. It serves the JavaScript frontend (with the
DSN injected) and exposes an endpoint that raises an error so you can see it
appear in Sentry.
"""

import os
import pathlib

import sentry_sdk
from flask import Flask, Response

DSN = os.environ.get("SENTRY_DSN") or None
ENVIRONMENT = os.environ.get("SENTRY_ENVIRONMENT") or "production"

if DSN:
    # The Flask integration is enabled automatically, so any unhandled error in
    # a view is reported to Sentry.
    sentry_sdk.init(dsn=DSN, environment=ENVIRONMENT, traces_sample_rate=0.0)

app = Flask(__name__)
_INDEX = pathlib.Path(__file__).with_name("index.html").read_text()


@app.get("/")
def index() -> Response:
    """Serve the frontend, injecting the DSN for the browser SDK."""
    html = _INDEX.replace("__SENTRY_DSN__", DSN or "")
    return Response(html, mimetype="text/html")


@app.get("/api/boom")
def boom() -> str:
    """Raise an error so the Python SDK reports it to Sentry."""
    raise ValueError("Boom from the Python backend (sentry-demo-app)")


@app.get("/healthz")
def healthz() -> str:
    """Liveness probe."""
    return "ok"


if __name__ == "__main__":
    # Bind to all interfaces inside the container so Juju can route to it.
    app.run(host="0.0.0.0", port=int(os.environ.get("APP_PORT", "8080")))  # noqa: S104
