# Releasing

`ordersim` should be published only when a clean install tells the same story as
the README.

## Release Gates

Before the first public release:

1. `python -m build` must produce valid distributions;
2. `python -m twine check dist/*` must pass;
3. a clean environment must install the built wheel and run
   `examples/canonical.py`;
4. the README, docs, and package behavior must agree about the default engine;
5. the release must have a short, concrete changelog.

The CI `package` job checks the first three gates on every PR.

## Recommended Publishing Path

Use PyPI Trusted Publishing from GitHub Actions rather than a long-lived API
token:

1. create the PyPI project and configure the GitHub repository, workflow file,
   and optional `pypi` environment as a trusted publisher;
2. build release artifacts in CI;
3. publish only from a tagged release workflow with `id-token: write`;
4. use GitHub release notes as the human-facing release summary.

The tagged `Release` workflow performs the publish step. Package validation
still belongs in normal CI; publishing credentials do not belong in the
repository.

## Versioning Direction

The first public version is `0.1.0`. It is appropriate once:

- installation instructions are final for the release;
- the preferred execution-engine story is settled;
- one canonical example runs from a clean install;
- the first release notes can say what a user can actually do.

Tag releases as `vX.Y.Z` so the tagged `Release` workflow builds the source
distribution, builds native wheels for every supported platform, and publishes
the combined artifacts through the configured PyPI Trusted Publisher.

## Native Wheels

`v0.1.0` ships the C++ engine in normal wheels. That matches the public engine
story: compiled replay is the ordinary default, while the Python engine is the
readable reference.

The normal package build now produces a platform wheel containing
`ordersim._matching_engine_cpp`. Before release, CI must build and test wheels
for every supported platform/Python pair that the project claims.

The `Wheels` workflow validates the platform matrix on pull requests and manual
runs:

| Platform runner | Target |
|---|---|
| `ubuntu-latest` | Linux wheels |
| `windows-latest` | Windows wheels |
| `macos-15-intel` | Intel macOS wheels |
| `macos-14` | Apple Silicon macOS wheels |

The tagged `Release` workflow repeats the same matrix before publishing. The
release target is CPython `3.11` and `3.12` on those platforms.

Source installs still need a compiler. Published wheels should make that an edge
case for ordinary users, not the default path.
