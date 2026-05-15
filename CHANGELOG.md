# Changelog

All notable public changes to `ordersim` are documented here.

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
