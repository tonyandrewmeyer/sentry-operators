# charmlibs.interfaces.sentry_dsn

A [charm library](https://documentation.ubuntu.com/charmlibs/) for the
`sentry_dsn` relation interface: integrate any charm with self-hosted Sentry
and receive a ready-to-use **DSN** over relation data, so the application — and
the charm itself — can report errors to Sentry without anyone creating a project
or copying a DSN by hand.

- **Provider** (`SentryDsnProvider`): the Sentry charm. On relation it
  provisions a Sentry project and key and publishes the DSN.
- **Requirer** (`SentryDsnRequirer`): any application charm. It optionally asks
  for a project name / platform / environment and reads back `.dsn`.

```python
from charmlibs.interfaces.sentry_dsn import SentryDsnRequirer

self.sentry = SentryDsnRequirer(self, project_name=self.app.name, platform="python")
self.framework.observe(self.sentry.on.dsn_changed, self._reconcile)
dsn = self.sentry.dsn
```

## Consuming it in a charm

Bundle the package into the charm (e.g. a `library` symlink to this directory)
and depend on it from the charm's `pyproject.toml`:

```toml
dependencies = ["charmlibs-interfaces-sentry-dsn"]

[tool.uv.sources]
"charmlibs-interfaces-sentry-dsn" = { path = "library", editable = true }
```

Declare the endpoint in `charmcraft.yaml`:

```yaml
requires:        # or `provides:` on the Sentry charm
  sentry-dsn:
    interface: sentry_dsn
    limit: 1
    optional: true
```
