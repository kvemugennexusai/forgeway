"""Forgeway's first real benchmark runner — see docs/benchmarking.md.

Scope (v0.1): one benchmark path, `vllm bench latency`, on local NVIDIA CUDA
or AMD ROCm hardware — the `vllm bench latency` command itself is identical
either way; only GPU telemetry sampling is vendor-specific (gpu_sampler.py
vs. rocm_gpu_sampler.py), selected by `run_vllm_bench_latency`'s
`gpu_vendor` parameter. Deliberately not a generic multi-model/multi-runtime
framework — there is exactly one concrete runner here
(`app.benchmark.vllm_runner`), no adapter interface, no registry. Add a
second runtime by writing a second module, not by generalizing this one
prematurely.

errors.py            BenchmarkError — the one expected failure mode
gpu_sampler.py        best-effort nvidia-smi telemetry sampling (memory, power)
rocm_gpu_sampler.py    the AMD equivalent, via rocm-smi
vllm_runner.py          orchestration: builds and runs the `vllm bench latency`
                       subprocess, sampling GPU telemetry (nvidia-smi or
                       rocm-smi, by `gpu_vendor`) while it runs
parser.py               turns vLLM's raw JSON output into a partial-tolerant,
                       typed result — never fabricates a missing metric
evidence.py              combines a parsed result + GPU samples + a ComputeTarget
                       into a PerformanceEvidence record
store.py                  saves/lists benchmark runs under a local results
                       directory (~/.forgeway/benchmarks by default)
cross_vendor.py            versioned BenchmarkProfile + comparability policy +
                       CrossVendorEvidenceRecord + BenchmarkRunner
                       (CudaVllmBenchmarkRunner/RocmVllmBenchmarkRunner) —
                       `forgeway bench-profile`/`forgeway compare-runs`
                       (docs/cross-vendor-validation.md). Additive only:
                       reuses vllm_runner.py/evidence.py completely
                       unchanged, never duplicates their metric semantics.
"""
