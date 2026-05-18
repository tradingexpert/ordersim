# Benchmarks

Benchmarks are small public scripts for answering narrow performance questions
without changing replay semantics.

## Execution-Engine Throughput

Run:

```bash
python benchmarks/execution_engine_throughput.py
```

This benchmark measures one thing only:

```text
ExecutionEngine.apply_event(MBOEvent)
```

It compares the pure Python `MatchingEngine` with `CppMatchingEngine` on the
same deterministic MBO workload. Each six-event cycle performs:

1. bid add;
2. ask add;
3. bid modify;
4. bid trade;
5. ask cancel;
6. bid cancel.

The cycle ends with an empty visible book, so repeated cycles do not accumulate
state from earlier cycles.

Example command-line controls:

```bash
python benchmarks/execution_engine_throughput.py --cycles 20000 --repeats 5 --warmups 1
```

The output reports median elapsed time and median events per second for each
engine. It also prints the C++ speedup when the compiled extension is available.

## What This Benchmark Does Not Measure

This first benchmark intentionally excludes:

- `Replay(...)` orchestration;
- strategy callbacks;
- latency models;
- `run_many(...)`;
- connector normalization;
- disk I/O.

Those measurements answer different questions and should live in separate
benchmarks. Mixing them into the first benchmark would make the raw execution
engine result harder to interpret.

## Interpreting Results

Benchmark results are machine-dependent. They are useful for comparing engines
on the same machine and same commit, not for making universal throughput
promises.

CI should verify benchmark code remains runnable; it should not enforce a fixed
speed threshold.
