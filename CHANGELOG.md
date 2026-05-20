# Changelog

All notable public changes to `ordersim` are documented here.

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
