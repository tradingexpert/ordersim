# Roadmap

This is a direction document, not a commitment. The dates are deliberately
omitted — the order of priorities is the useful information. Open issues and
discussions are the working surface; this file exists so a new reader can see
where the project is going without reading the whole tracker.

## Near term — what's actively being shaped

These are the questions that are likely to land first, in roughly the order
they will probably arrive.

- **Maker–taker fee modeling.** See [#40](https://github.com/tradingexpert/ordersim/issues/40).
  The fee model is currently a uniform schedule; venue-realistic maker/taker
  separation is needed before fee-sensitive strategy comparisons become
  honest.
- **Limit-order fill-connected strategies.** See [#39](https://github.com/tradingexpert/ordersim/issues/39).
  Strategies that route their next action off the result of a fill — partial,
  passive, or cancelled — are first-class research subjects. The gateway API
  should make this ergonomic without leaking event-loop concerns into the
  strategy code.
- **Engine equivalence depth.** The Python and C++ engines must produce
  identical event logs against the equivalence fixtures. New fixtures are
  added as new fill paths get exercised. Equivalence is a release gate, not
  an aspiration.

## Middle distance — directions, not commitments

- **Venue-specific matching behavior.** See the open
  [Discussion](https://github.com/tradingexpert/ordersim/discussions). The
  honest version of this is not a "supports venue X" matrix but a small set
  of named matching primitives (price–time, pro-rata, price improvement
  variants) that can be composed to match real venues, with the residual
  uncertainty stated.
- **Hidden-liquidity modeling.** See the open
  [Discussion](https://github.com/tradingexpert/ordersim/discussions). The
  unhelpful version of this is a tunable knob. The useful version is an
  explicit assumption surface that a study can declare and a reviewer can
  audit.
- **More batch-ingest paths through the C++ engine** for callers that own
  the event loop, while keeping the audited per-event `Replay(...)` path as
  the reference for valuation marks.
- **Examples that mirror Trading Reality essays.** Each essay that turns on
  an execution mechanism should have a runnable companion in
  `examples/`. The
  [latency demo](examples/latency_demo.py) is the template; adverse
  selection and queue-position essays are the natural next companions.

## Out of scope — deliberately, not yet

`ordersim` is a simulator. It will not turn into:

- A general-purpose backtesting framework. You own the strategy loop.
- A live trading system or order-routing gateway. The Python-facing API is
  shaped so a production gateway can mirror it; the bridging code is yours.
- A signal library or alpha repository.
- A speed-first HFT framework. Compiled speed is welcome only when it
  preserves observable behavior.

These exclusions are how the surface stays inspectable.

## Editorial context

The conceptual frame for why these choices were made — and why "what an
order did, in order, against this replay" is the unit of research — lives at
[Markets in Production](https://marketsinproduction.com/ordersim/) and the
[Trading Reality](https://www.tradingreality.com) publication. The roadmap
should be read alongside that context, not separately from it.

## Contributing

Open a [Discussion](https://github.com/tradingexpert/ordersim/discussions)
for anything that does not yet look like a concrete bug or feature. Issues
labeled
[`good first issue`](https://github.com/tradingexpert/ordersim/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
are the lowest-friction entry points. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the working agreement.
