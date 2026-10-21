# Saved NVIDIA/AMD evidence replay

The CLI can import `results/nvidia-run.json` and `results/amd-run.json` directly
as evidence envelopes. It does not mutate them, infer capabilities from benchmark
success, or turn offline benchmark results into live placement validation.

The saved measurements remain:

| Target | End-to-end latency | P99 latency | Output throughput | Average GPU power |
| --- | --- | --- | --- | --- |
| NVIDIA GB10 | 2099.08 ms | 2099.91 ms | 60.98 tokens/s | 12 W |
| AMD Radeon RX 9070 XT | 792.8 ms | 795.02 ms | 161.45 tokens/s | 13 W |

These are offline `vllm bench latency` runs for `Qwen/Qwen2.5-1.5B-Instruct`,
BF16, input 512 tokens, output 128 tokens, concurrency 1, tensor parallelism 1,
one warmup and three measured iterations. They do not measure streaming TTFT.
The NVIDIA record has no measured GPU memory capacity or peak-memory metric;
its target's 0 GB memory is an unavailable-data placeholder. AMD reports 15.9 GB
per device and a measured peak of 15529.7 MB. Runtime builds and host environments
differ; use `forgeway compare-runs` to inspect comparability limitations rather
than assuming that matching profile names imply identical environments.

Before meaningful placement replay:

1. Extract each envelope's `target` into a separate JSON file, retaining its exact
   ID (`local-nvidia-0b4cd5b53c81` / `local-amd-2c2f28ae4a9b`). Keep the original
   result files unchanged. Supply verified capability metadata in these separate
   target files: NVIDIA usable memory, supported precisions on both targets,
   runtime support/qualification, and relevant interconnect information. Both
   saved targets have empty precision lists, unknown runtime support, and an
   unprobed interconnect. The engine currently rejects unsupported precision;
   unknown runtime metadata is not proof of runtime qualification.
2. Define a workload with ID exactly `Qwen/Qwen2.5-1.5B-Instruct` and requirements
   appropriate to the measured configuration. Supply justified weights/KV-cache
   footprints, BF16 precision, throughput/latency SLOs, and policy allowing these
   local lab locations/vendors. The existing Llama70B example is not this workload.
   Do not relabel the measurements as another workload or configuration.
3. Supply a documented, comparable hourly cost basis before interpreting cost
   scores or rankings. Both envelopes explicitly say `cost_basis: not_available`;
   both embedded target prices are zero-value, zero-confidence placeholders.
   Importing evidence does not supply pricing, and the unchanged engine may still
   calculate with placeholder prices. Such output is not a valid cost comparison.
4. Run the README's `--targets-only` command with the prepared workload and target
   files. Inspect rejected-target reasons, selected evidence references, SLO
   results, warnings, and qualifications. Ambient local benchmark runs remain
   candidates; point `FORGEWAY_BENCH_DIR` at an empty directory for an isolated
   saved-evidence replay.

CLI regression tests validate loading, routing, errors, and preservation of saved
measurements. Synthetic test cases do not establish live placement correctness,
production SLO compliance, or a NVIDIA/AMD placement winner. Live validation of
any resulting recommendation remains a separate prerequisite.

## Illustrative replay outcome

Replay of the captured live evidence completed using the saved-input CLI. Six
runs covered original metadata, annotations limited to BF16/vLLM for the captured
configuration, and a separate hypothetical-memory scenario, each at 2,500 ms and
1,000 ms P99 limits with a 50 output tokens/second minimum.

Original metadata caused hard rejections: both precision lists were empty and
DGX memory remained unresolved. With the precision annotation, AMD met both SLOs
but unavailable pricing failed the confidence gate. With a separately labeled
hypothetical 16 GB NVIDIA capacity, both targets passed hard feasibility; NVIDIA
met the 2,500 ms limit but failed 1,000 ms, while AMD met both. The illustrative
workload used a modeled 6 GB footprint, not a measured requirement.

Recommendations were withheld: original zero-confidence pricing yields 0%
prediction confidence, below the unchanged 70% requirement. No candidate reached
ranking; no cost savings were established. DGX memory remains unresolved. The
hypothetical capacity is not verified hardware capacity, and these replays do not
validate live placement, current capacity, or production serving SLOs. Private
replay inputs, candidate records and reports are kept outside Git.

At replay completion, the full backend suite passed 392 tests. Subsequent review
fixes added boundary, collision, storage-isolation and CLI-to-engine regressions;
the full suite now passes 415 tests. All six replay CLI decisions matched direct
`run_decision` results, source hashes remained unchanged, and no fresh GPU
benchmarks were run. Meaningful ranking and objective-weight sensitivity remain
pending verified memory, actual requirements and credible comparable pricing.
