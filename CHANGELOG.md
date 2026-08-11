# Changelog

All notable public changes to `ordersim` are documented here.

## Unreleased

- Added an optional Binance USD-M recorder for synchronized raw depth,
  aggregate-trade, book-ticker, snapshot, and RPI evidence.
- Added connection manifests and explicit diff-depth sequence-gap records,
  while keeping lower-fidelity capture separate from modeled MBO replay.
- Added a typed, streaming reader for completed Binance captures with exact
  depth, aggregate-trade, and book-ticker records.
- Added snapshot bridging and `pu`/`u` continuity validation for standard
  Binance diff-depth segments.
- Added rate-budgeted Binance individual-trade capture with overlapping REST
  polls, late-ID tolerance, trade-ID deduplication, explicit gap records, and
  RPI trade flags.
- Added the real-time Binance individual `@trade` stream to the main capture,
  with explicit trade-ID discontinuity records; aggregate trades remain
  reconciliation evidence.
- Added typed `BinanceRawTrade` records alongside aggregate trades so the more
  detailed public evidence is available to future reconstruction models.
- Added deterministic Binance L2-to-virtual-MBO reconstruction with explicit
  queue-conservative and queue-optimistic policies, exact quantity scaling,
  and canonical `MBOEvent` output.
- Added a streaming reconstruction study that aligns individual trades to
  depth intervals, validates joinable book-ticker states, preserves reconnect
  boundaries, and reports inferred flow and model sensitivity.

## 0.1.3 - 2026-05-20

- Improved default replay throughput by precompiling canonical event streams
  once and using the C++ batch path during replay advancement while preserving
  fills and valuation marks.
- Moved valuation mark types and compact mark iteration into
  `ordersim.valuation`, keeping public imports stable while making economics
  easier to read.
- Broadened README, PyPI metadata, and GitHub topics around order-book replay,
  latency-aware fill simulation, execution modeling, and market microstructure.

## 0.1.2 - 2026-05-15

- Added a visual latency demo showing the same strategy taking different fill
  paths under different entry latency.
- Sharpened the README first screen around the path from order intent to fill.
- Updated GitHub Actions to current Node 24-era action releases and removed
  duplicate release-time wheel builds.

## 0.1.1 - 2026-05-15

- Updated the public install text after the first PyPI release.

## 0.1.0 - 2026-05-15

- Added an inspectable replay API with full order-intent logs, fill ledgers,
  equity curves, and deterministic multi-strategy comparison support.
- Added queue-aware Python and packaged C++ execution engines, with the C++
  engine used by default and shared equivalence fixtures guarding behavior.
- Added canonical CSV, Parquet, Databento MBO, and synthetic data sources plus
  a connector -> Parquet -> replay workflow for repeated research runs.
- Added explicit latency models, timezone guidance, assumptions, architecture
  notes, contributor guidance, release checks, and cross-platform native-wheel
  validation.
