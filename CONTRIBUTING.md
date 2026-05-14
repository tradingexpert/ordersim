# Contributing

`ordersim` is early. The best contributions are small, explicit, and easy to
audit.

## Good First Contributions

- Add a data connector with a tiny public fixture.
- Improve schema documentation.
- Add a focused replay test.
- Clarify an assumption.
- Improve the canonical example once the package skeleton lands.

## Development Workflow

All changes should go through a pull request. `main` is protected and requires
CI to pass before merge.

Use branch names that describe the type of change:

- `feature/...` for new behavior, docs, examples, or package structure;
- `fix/...` for bug fixes;
- `docs/...` only when the branch is purely documentation and does not affect
  package behavior.

Keep pull requests small enough to review in one sitting. A good PR usually has
one purpose, a short description, tests, and clear notes about any assumptions
it changes.

Before opening a PR, run:

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest
```

`pytest` includes coverage by default and currently enforces a minimum coverage
threshold. If a change lowers coverage, add focused tests rather than lowering
the threshold.

Draft PRs are welcome while a change is still taking shape. Mark a PR ready
when it is scoped, documented, tested, and CI is green.

Preferred merge style is squash merge, so public history stays readable.

## Project Boundaries

Please do not add:

- live-trading connectors;
- signal-generation logic;
- private broker/account formats;
- large market-data files;
- performance shortcuts that silently change fill behavior.

## Connector Contributions

A connector should:

- implement the public `DataSource` protocol once it lands;
- document input and normalized schemas;
- state timestamp semantics and units;
- include a tiny fixture or generator;
- add at least one deterministic replay test.

Optional vendor SDKs should be installed through extras, not core
dependencies.

## Engineering Style

Prefer code that can be read in a debugger. Public APIs should be typed,
documented, and stable. See `docs/engineering-standards.md` before starting a
larger change.
