# Architecture

`ordersim` is deliberately small. Strategies do not talk to connectors or
matching engines directly; they talk to the public gateway. Replay coordinates
the rest.

## Component View

```mermaid
flowchart LR
    evidence["Source evidence<br/>observed MBO or L2 + trades"]
    integration["Connector or<br/>named reconstruction model"]
    canonical["Canonical MBOEvent stream"]
    replay["Replay"]
    recording["RecordingGateway"]
    strategy["Strategy"]
    gateway["ReplayGateway"]
    engine["ExecutionEngine"]
    python["MatchingEngine<br/>Python reference"]
    cpp["CppMatchingEngine<br/>preferred when available"]
    valuation["Valuation marks"]
    result["ReplayResult<br/>fills, order log, economics"]

    evidence --> integration
    integration --> canonical
    canonical --> replay
    replay --> recording
    recording <--> strategy
    recording --> gateway
    gateway --> engine
    engine --> python
    engine --> cpp
    gateway --> valuation
    valuation --> result
    gateway --> result
    recording --> result
```

The main boundaries are:

- observed-MBO connectors normalize order-level data directly into `MBOEvent`;
- lower-fidelity sources require a named reconstruction model before they
  reach the canonical boundary;
- strategies depend on `OrderGateway`, not on storage or engine internals;
- replay normalizes inputs once, chooses an execution engine, and gathers
  results;
- valuation marks are collected during replay and consumed by economics;
- the Python engine defines behavior; the C++ engine must match it.

## Data Fidelity Paths

The replay core is independent of venue, asset class, and data vendor. Two data
paths converge on the canonical `MBOEvent` boundary.

Observed order-level data takes the direct path:

```mermaid
flowchart LR
    raw["Observed order-level source"]
    normalize["MBO connector"]
    materialize["write_parquet(...)"]
    parquet["Canonical Parquet"]
    source["ParquetSource"]
    replay["Replay"]

    raw --> normalize --> materialize --> parquet --> source --> replay
```

Direct connector replay is supported, but repeated research should normally
materialize canonical Parquet once and replay from it thereafter. See
`docs/data-guide.md`. Databento is the current reference connector for this
path; CSV and Parquet support the normalized canonical schema.

Price-level data takes a longer, explicit path:

```mermaid
flowchart LR
    venue["Venue L2 + individual trades"]
    capture["Raw capture"]
    source["Typed L2 source"]
    model["Named reconstruction model<br/>explicit queue policy"]
    modeled["Modeled MBOEvent stream"]
    parquet["Canonical Parquet + model manifest"]
    replay["Replay"]

    venue --> capture --> source --> model --> modeled --> parquet --> replay
```

This is the path that currently enables Binance crypto data: aggregated venue
data reaches the same canonical event and execution-engine boundary as observed
MBO, but only after a named model makes the missing order-level structure
explicit. The architecture itself is not Binance- or crypto-specific. New
reconstruction policies should compete on paired-L3 or live-fill prediction,
not on undocumented claims of realism.

Capture code may live beside connectors because it owns venue I/O and source
schemas. Capture alone is not a `DataSource`: observed L2 rows must not be
presented as exchange-native MBO. The reconstruction model owns that
lower-fidelity assumption and preserves a study manifest describing how its
events were inferred. The current reference implementation uses
`BinanceCaptureSource` as the typed, sequence-validated L2 boundary and
`BinanceMBOReconstructor` to emit modeled canonical events for one
snapshot-anchored segment. The capture source itself does not implement the
canonical MBO `DataSource` protocol.

## One Replay Run

```mermaid
sequenceDiagram
    participant Strategy
    participant RecordingGateway
    participant ReplayGateway
    participant LatencyModel
    participant ExecutionEngine
    participant Events as "MBOEvent stream"

    Strategy->>RecordingGateway: advance_to(ts)
    RecordingGateway->>ReplayGateway: advance_to(ts)
    loop each event up to ts
        ReplayGateway->>Events: read next event
        ReplayGateway->>ExecutionEngine: apply_event(event)
        ExecutionEngine-->>ReplayGateway: passive fills
    end
    ReplayGateway-->>RecordingGateway: passive fills
    RecordingGateway-->>Strategy: passive fills

    Strategy->>RecordingGateway: place_limit(...)
    RecordingGateway->>ReplayGateway: place_limit(...)
    ReplayGateway->>LatencyModel: sample(now_ns)
    LatencyModel-->>ReplayGateway: entry latency
    ReplayGateway->>ExecutionEngine: place_limit(...)
    ExecutionEngine-->>ReplayGateway: order result + active fills
    ReplayGateway-->>RecordingGateway: order result
    RecordingGateway-->>Strategy: order result
```

The order log is recorded at the gateway boundary, so it captures strategy
intent as well as resulting fills.

## Execution Engines

```mermaid
flowchart TD
    protocol["ExecutionEngine protocol"]
    python["MatchingEngine<br/>plain Python reference"]
    cpp["CppMatchingEngine<br/>pybind11 wrapper"]
    equivalence["Public equivalence fixtures"]

    protocol --> python
    protocol --> cpp
    python --> equivalence
    cpp --> equivalence
```

`Replay(...)` prefers `CppMatchingEngine` when the extension is importable,
because it preserves the same public behavior while avoiding the Python hot
loop. `MatchingEngine` remains the reference implementation because it is the
easiest place to inspect queue behavior and define equivalence.

Inside that reference engine, public market-data mutations are kept separate
from strategy-order matching helpers so the book lifecycle can be read in the
same order the simulator applies it.

Compiled-engine changes are accepted only when they match the public Python
fixtures.

## Multi-Strategy Replay

```mermaid
flowchart LR
    data["Immutable event tuple"]
    replay["Replay.run_many(...)"]
    a["strategy A<br/>own gateway + engine"]
    b["strategy B<br/>own gateway + engine"]
    c["strategy C<br/>own gateway + engine"]
    ra["ReplayResult A"]
    rb["ReplayResult B"]
    rc["ReplayResult C"]

    data --> replay
    replay --> a --> ra
    replay --> b --> rb
    replay --> c --> rc
```

`run_many(...)` does not let strategies share mutable execution state. `Replay`
first builds one immutable canonical event tuple; each strategy then receives
its own gateway, engine, order log, fills, and portfolio summary while reading
that same tuple. The intended property is solo-equivalence: running a strategy
inside `run_many(...)` should match running it alone on the same input.

## Where To Extend

| Goal | Extension point |
|---|---|
| Support a new vendor format | add a connector under `ordersim/connectors/` |
| Record lower-fidelity venue evidence | add a capture tool beside the venue connector |
| Infer order-level events from L2 | add a named reconstruction model and manifest |
| Add a latency assumption | implement `LatencyModel` |
| Add an execution implementation | implement `ExecutionEngine` and prove equivalence |
| Change strategy logic | use only the `OrderGateway` surface |

If a proposed change crosses several of those rows at once, pause and check
whether it is really one feature or several.

## Related Docs

- Data workflow: `docs/data-guide.md`
- Connector details: `docs/connectors.md`
- Engine behavior: `docs/execution-engines.md`
- Public schema: `docs/schema.md`
- Assumptions: `docs/assumptions.md`
