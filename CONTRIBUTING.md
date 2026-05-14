# Contributing

`ordersim` is early. The best contributions are small, explicit, and easy to
audit.

## Good First Contributions

- Add a data connector with a tiny public fixture.
- Improve schema documentation.
- Add a focused replay test.
- Clarify an assumption.
- Improve the canonical example once the package skeleton lands.

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

