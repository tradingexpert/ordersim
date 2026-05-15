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

The release workflow should be added when `v0.1.0` is ready to publish, not
before. Until then, package validation belongs in normal CI and publishing
credentials do not belong in the repository.

## Versioning Direction

The current package version is `0.0.0` because the public API is still being
prepared. Move to `0.1.0` only when:

- installation instructions are final for the release;
- the preferred execution-engine story is settled;
- one canonical example runs from a clean install;
- the first release notes can say what a user can actually do.

## Open Packaging Decision

The remaining release-shaping decision is how the C++ engine ships:

- **pure-Python first release**: easiest install path, with the C++ engine still
  source-built from the repo;
- **native wheels in the first release**: stronger default-engine story, but it
  requires reliable wheel builds across supported platforms before publishing.

The current package job validates the pure-Python wheel that the present build
configuration emits. If the project chooses native wheels for `v0.1.0`, the
build system and CI matrix need to change before release.

The project should choose one path explicitly before `v0.1.0`. The README should
not promise more than the published artifacts provide.
