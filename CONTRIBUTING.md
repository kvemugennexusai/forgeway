# Contributing to Forgeway

Forgeway is an early, public technical preview. This doc covers local
setup, how to run the checks a change is expected to pass, and how to
extend the three things most contributions will touch: benchmark
evidence, discovery adapters, and workload fixtures.

## Project philosophy (read this first)

Two rules shape every review in this repo:

1. **Never fabricate a number.** A value is either directly measured, a
   plain arithmetic derivation of a measurement, or an explicitly labeled
   model/estimate (`provenance: MODELED`). Nothing here guesses a metric
   and presents it as `MEASURED` or `PUBLISHED`. If you can't determine a
   real value, leave the field honestly empty/placeholder and say so,
   rather than inventing something plausible.
2. **One decision engine, every caller.** `app/engine/decision.py::run_decision()`
   is the only function that turns a workload into a recommendation — the
   web API, the estate dashboard, every scenario preset, and `forgeway analyze`
   all call it. Never re-implement feasibility, scoring, or ranking logic
   in a second place; extend the one engine instead.

See [`docs/architecture.md`](docs/architecture.md) for the core-vs-product
boundary these rules are built around.

## Local setup

Two independent projects, two terminals.

**Backend** (from `api/`):

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt   # editable-installs this package and
                                  # registers the `forgeway` console script
uvicorn app.main:app --reload --port 8000
```

**Frontend** (from `web/`):

```bash
npm install
npm run dev
```

Open `http://localhost:3000`. `web/.env` already points
`NEXT_PUBLIC_API_BASE_URL` at `http://localhost:8000` — no secrets in
either project's setup; nothing here talks to a real cloud provider.

## Running the checks

A change is expected to pass all of these before a PR:

```bash
# backend tests
cd api && source .venv/bin/activate && pytest tests/ -v

# frontend type check, lint, and build
cd web && npx tsc --noEmit && npm run lint && npm run build
```

**There is currently no Python linter or type checker configured**
(no ruff/black/mypy) — only `pytest`. If you introduce one, do it as its
own PR with its own pass over the existing code, not bundled into an
unrelated change, since retrofitting one across the whole codebase is a
non-trivial amount of churn on its own.

**Backend dependencies have no lockfile.** `api/pyproject.toml` declares
open-ended lower bounds (`fastapi>=0.115`, `pydantic>=2.9`, etc.) with no
committed `pip freeze`/`pip-compile` snapshot — unlike `web/package-lock.json`,
which is committed. This has been verified to install and pass the full
test suite against `fastapi==0.141.1`, `pydantic==2.13.5`, `uvicorn==0.52.4`,
`pyyaml==6.0.3`, `pytest==9.1.1` on Python 3.14; if a fresh install ever
breaks against newer releases of these, that's a real regression worth a
lockfile or upper bounds, not an environment problem on your end.

**Don't run `npm run build` while `npm run dev` is also running** against
the same `web/` checkout — both write to `.next/` and a build can corrupt
the dev server's cache mid-session (you'll see a
`__webpack_modules__[moduleId] is not a function` error and an unstyled
page). If that happens: stop the dev server, `rm -rf web/.next`, and
restart `npm run dev`.

## How to add benchmark evidence

"Benchmark evidence" means a real `PerformanceEvidence` record
(`forgeway/v0.1` — [`docs/schemas.md`](docs/schemas.md#3-performanceevidence)).
There are two ways to produce one:

1. **Run it for real**: `forgeway bench` on an NVIDIA GPU
   ([`docs/benchmarking.md`](docs/benchmarking.md)) — the only benchmark
   path that exists today. It saves to `~/.forgeway/benchmarks/*.json` and
   can be imported into the web demo via `/import`
   ([`docs/importing-results.md`](docs/importing-results.md)).
2. **Add a fixture row** for this demo's own catalog: an entry in
   `api/app/fixtures/performance_profiles.json`, keyed by
   `(workload_id, target_id)` — see the existing two rows (H100
   `MEASURED`, MI300X `MODELED`) for the shape. Every value needs a real
   `confidence`, `provenance`, and `source` string that honestly describes
   where the number came from; don't add a `MEASURED` row unless it
   actually reflects real telemetry or a real benchmark run.

Either way, if you're tagging evidence with an existing workload's id
(`--workload-id`, or a fixture row's `workload_id`), **that's only honest
when the benchmarked/modeled configuration actually corresponds to that
workload** (same model family, same parameter count) — see
`docs/importing-results.md#tagging-evidence-with-a-real-workload-id` for
why this matters and what can go wrong if it isn't true.

The engine only scores evidence carrying its two canonical metric keys
(`throughput_tokens_per_s_per_replica`, `p99_latency_ms_per_replica` —
`app.core.schemas.THROUGHPUT_METRIC_KEY`/`LATENCY_METRIC_KEY`); see
[`docs/decision-engine.md`](docs/decision-engine.md) for how evidence is
selected once it's comparable.

## How to add a discovery adapter

See [`docs/adding-an-accelerator.md`](docs/adding-an-accelerator.md) —
one new class implementing `DiscoveryAdapter`
(`api/app/discovery/adapter.py`), one line registering it in
`api/app/cli/main.py`'s `ADAPTERS` list, tests that mock the vendor's
query tool output (no real hardware required to run the suite), and a
docs update. AMD ROCm is the next one on `ROADMAP.md`.

## How to add a workload fixture

A workload is one entry in `api/app/fixtures/workloads.json` — see any
existing entry for the full shape (`slo`, `policy`, `objective_weights`,
`current_placement`, etc.). Conventions to follow:

- `id`: `wl-<short-name>`, matching the existing entries.
- `current_placement` needs real-looking, internally consistent numbers
  (a `cost_per_hr` that's plausible for `target_id`'s pricing, a
  `measured_p99_latency_ms` consistent with the SLO it's supposedly
  meeting) — this is what the estate dashboard and `/workloads` render
  as the workload's starting point.
- **A new workload with no `performance_profiles.json` row for any
  target other than its own `current_placement` will honestly show every
  other target as infeasible with "no trustworthy performance evidence on
  file"** — this is the correct, expected behavior (see
  `docs/decision-engine.md`), not a bug. Add rows to
  `api/app/fixtures/performance_profiles.json` for whichever
  `(workload_id, target_id)` pairs you want the engine to actually be able
  to evaluate and rank.
- After adding one, run the backend tests — nothing should break, since a
  new workload is additive — and check it renders correctly on
  `/workloads` and `/analyze` in the running web demo.
- `web/lib/types.ts` mirrors `api/app/models.py` by hand; a new *field*
  (not a new fixture row) needs updating there too.

## PR expectations

- Every backend change: `pytest tests/ -v` green, and a new test for new
  behavior — this codebase aims to keep engine logic (`app/core/engine/`,
  `app/engine/`) fully tested, and PRs are expected to keep it that way,
  not introduce a gap.
- Every frontend change: `tsc --noEmit`, `npm run lint`, and `npm run build`
  clean.
- If you change `api/app/models.py`, check whether `web/lib/types.ts`
  needs the same change — there's no code generation keeping them in
  sync.
- Update the relevant doc in `docs/` in the same PR as the behavior it
  describes — a doc that overclaims what the code does is treated as a
  bug in this repo, not a nitpick.
- Don't add a fabricated `MEASURED` or `PUBLISHED` value anywhere, in
  fixtures or in code, to make a demo look more complete — see "Project
  philosophy" above.
- No secrets, no machine-specific absolute paths, no committed build
  artifacts (`.next/`, `__pycache__/`, `*.egg-info/` are already
  gitignored — keep it that way for anything new).
- Keep PRs scoped to one thing; a large feature is easier to review as a
  short design note or issue first.
