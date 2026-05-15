# Engineering Standards

`ordersim` should feel small, explicit, and inspectable. The code is allowed to
be slower than a compiled HFT framework. It is not allowed to be mysterious.

## Design Principles

1. Public behavior is more important than implementation cleverness.
2. A reader should be able to trace one order from strategy call to fill without
   jumping through dynamic indirection.
3. Every data schema should be documented in one place.
4. Every realism assumption should be named.
5. Every optimization must preserve semantics.

## Public API Rules

- Keep the gateway API small.
- Use type hints on every public symbol.
- Use dataclasses and protocols for public contracts.
- Prefer plain functions and explicit objects over decorators, metaclasses, or
  generated APIs.
- Separate public modules from internal modules.
- Do not rename public imports without a deprecation path.

## Code Style Rules

- Use clear names even when they are longer.
- Prefer early validation over implicit coercion.
- Keep functions short enough to inspect in one screen when practical.
- Use comments to explain domain assumptions, not obvious Python mechanics.
- Avoid global mutable state.
- Avoid hidden I/O in constructors.
- Avoid print statements in library code; use returned events or logging hooks.
- Keep randomness seedable.

## Data Rules

- All public timestamps are UTC Unix-epoch integer nanoseconds.
- All public sizes are integers.
- Public prices should be exact: integer ticks or `Decimal`.
- Data connectors must state source units, source timezone, UTC-normalization
  rules, timestamp source, and whether events are exchange-time or receive-time.
- Examples must run without private data or paid data.
- Large market-data files do not belong in the repo.

## Matching And Replay Rules

- The Python matching engine is the reference implementation.
- Queue behavior must be tested with small, readable fixtures.
- Passive fills must be observable.
- Cancels must be observable.
- `run_many` must preserve solo-equivalence.
- Replay ordering must be deterministic for identical input and seed.
- Lower-fidelity modes must be named as lower fidelity.

## Engine Policy

Compiled execution engines are allowed only as equivalent implementations.

An acceptable compiled execution engine:

- produces the same fills as the Python engine on public fixtures;
- preserves final position and execution-summary accounting;
- preserves own resting-order snapshots;
- preserves equity-curve valuation points;
- preserves observable order-intent behavior;
- passes the public execution-equivalence harness;
- is optional at install time;
- fails gracefully when unavailable.

An unacceptable engine:

- drops queue position to gain speed;
- ignores response latency;
- skips passive fill generation;
- changes cancel behavior;
- produces different results without making that a named model.

## Documentation Rules

Every public feature needs:

- what it does;
- what it assumes;
- one minimal example;
- at least one test reference.

Every connector needs:

- source schema;
- normalized schema;
- timestamp semantics;
- price and size units;
- known lossy conversions.

Every latency or fill model needs:

- parameters;
- randomness behavior;
- failure modes;
- when not to use it.

Latency models must keep entry and response latency explicit. They should not
collapse the two legs into one opaque number at the public API boundary.

## Extraction Checklist

Before moving a file from the private repo:

- remove strategy-specific imports;
- remove account, broker, or data-infrastructure coupling;
- replace private defaults with explicit constructor arguments;
- add type hints where public;
- add or preserve tests;
- document any behavior that depends on exchange or data-source convention;
- verify no generated artifacts, CSVs, parquets, caches, or private scripts are
  included.

The public repo should look like a library that happened to come from real
research, not a private trading repo with the sensitive parts deleted.
