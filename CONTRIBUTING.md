# Contributing

This is a monorepo of Juju charms for self-hosted Sentry.

## Layout

```
charms/<charm-name>/   # one charmcraft project per charm
rocks/                 # reserved for auxiliary Rockcraft images (currently empty)
releases/              # bundle that wires the topology together
terraform/             # all-in-one Terraform module
docs/                  # tutorial / how-to / reference / security
demos/                 # executable end-to-end demo
.github/workflows/     # CI (lint+unit, integration, release)
```

The workloads run upstream's published OCI images attached as charm resources;
the charms do not build their own images, so there are no rocks to pack today.

## Developing a charm

Each charm is a standard `ops` charm with a `tox.ini`:

```bash
cd charms/<charm-name>
tox -e format       # apply ruff formatting
tox -e lint         # ruff + codespell
tox -e static       # pyright type checks
tox -e unit         # ops.testing (Scenario) unit tests
tox -e integration  # jubilant integration tests against a live model
charmcraft pack     # build the .charm
```

## Pre-commit

Install the [pre-commit](https://pre-commit.com/) hooks so formatting, linting,
spelling and **every charm's unit tests** run automatically before each commit;
a commit is blocked if any of them fail:

```bash
uv tool install pre-commit   # or: pip install pre-commit
pre-commit install           # enable the git hook
pre-commit run --all-files   # run them on demand
```

The unit-test hook runs [`scripts/run-unit-tests.sh`](scripts/run-unit-tests.sh),
which you can also run directly.

## Conventions

- Charms target Juju 3.6+ and `ops ~=3.7`; Python 3.10+ (packed and tested on
  Ubuntu 24.04 / Python 3.12).
- Generated or long-lived secrets are stored in Juju secrets, never in config
  or relation data in the clear.
- Workload ports are opened with `Unit.set_ports` so the per-application
  Kubernetes service routes to them.
- All charms integrate with COS (metrics, logs, dashboards, tracing).
- `metadata.yaml` / `config.yaml` / `actions.yaml` are generated from
  `charmcraft.yaml` at pack time — edit `charmcraft.yaml`, not the generated
  files.
- Conventional commits are appreciated but not required.

## License

By contributing you agree your contributions are licensed under Apache-2.0.
