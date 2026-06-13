# Contributing

This is a monorepo of Juju charms and Rockcraft rocks for self-hosted Sentry.

## Layout

```
charms/<charm-name>/   # one charmcraft project per charm
rocks/<rock-name>/     # one rockcraft project per OCI image
releases/              # bundle + Terraform module that wire the topology
docs/                  # tutorial / how-to / reference
.github/workflows/     # CI
```

## Developing a charm

Each charm is a standard `ops` charm with a `tox.ini`:

```bash
cd charms/<charm-name>
tox -e format     # apply ruff formatting
tox -e lint       # ruff + codespell
tox -e static     # type checks
tox -e unit       # ops.testing (Scenario) unit tests
tox -e integration  # jubilant integration tests against a live model
charmcraft pack   # build the .charm
```

## Building a rock

```bash
cd rocks/<rock-name>
rockcraft pack
```

## Conventions

- Charms target Juju 3.6+ and `ops` 2.x, Python 3.12.
- Generated/long-lived secrets are stored in Juju secrets, never in config or
  relation data in the clear.
- All charms integrate with COS (metrics, logs, dashboards, tracing).
- Conventional commits are appreciated but not required.

## License

By contributing you agree your contributions are licensed under Apache-2.0.
