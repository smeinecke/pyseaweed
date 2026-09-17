# Contributing

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/smeinecke/pyseaweed.git
cd pyseaweed
uv sync
```

## Validate

```bash
make validate   # ruff format+lint, radon, bandit, pyright, vulture
make test       # unit tests
make test-cov   # unit tests with coverage (must stay at 100% for the package)
make docs       # build Sphinx docs (warnings are errors)
```

## Integration tests

Integration tests run against a live SeaweedFS in Docker:

```bash
make test-integration-local   # starts container, runs tests, removes container
```

## Pull requests

- Keep changes in logically grouped commits.
- All checks (`make validate`, unit tests, integration tests, docs build)
  run in CI on every PR and must pass.
- New public API needs unit tests, an integration test where possible,
  and a changelog entry in `docs/changes.rst`.

## Releases

Releases are cut from tags. The tag must match `src/pyseaweed/version.py`:

```bash
# bump __version__, update docs/changes.rst, then:
git tag vX.Y.Z && git push origin vX.Y.Z
```
