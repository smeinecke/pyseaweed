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

`weed-up` also starts a toxiproxy sidecar (admin API on :8474, proxies
on :29333 -> master and :28888 -> filer) used by the live
fault-injection tests in `tests/integration/test_fault_injection.py`.

## Mutation testing

Mutation testing with mutmut is available but not part of the PR gate —
it runs weekly in CI and on demand:

```bash
make mutation   # mutates src/, runs the unit suite per mutant
```

`mutmut results` lists surviving mutants; `mutmut browse` inspects them.
New code should kill its mutants — add tests or mark intentional
survivors with `# pragma: no mutate`.

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
