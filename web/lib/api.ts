import type {
  AnalyzeRequestBody,
  ComputeTarget,
  DecisionRecord,
  EstateSummary,
  PerformanceEvidence,
  ScenarioCatalogEntry,
  ScenarioComparison,
  ScenarioType,
  Workload,
  WorkloadListItem,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** A validation failure from an import endpoint — carries FastAPI's
 * structured per-field detail (docs/importing-results.md) rather than
 * just a flattened message, so the UI can show which field(s) failed and
 * why instead of one opaque string. */
export class ImportValidationError extends Error {
  readonly issues: { loc: (string | number)[]; msg: string }[];

  constructor(issues: { loc: (string | number)[]; msg: string }[]) {
    super(issues.map((i) => `${i.loc.filter((p) => p !== "body").join(".")}: ${i.msg}`).join("; "));
    this.name = "ImportValidationError";
    this.issues = issues;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (res.status === 422) {
    const body = await res.json();
    throw new ImportValidationError(body.detail ?? []);
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${init?.method ?? "GET"} ${path} failed (${res.status}): ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  estateSummary: () => apiFetch<EstateSummary>("/api/estate/summary"),

  listComputeTargets: () => apiFetch<ComputeTarget[]>("/api/infrastructure"),
  getComputeTarget: (id: string) => apiFetch<ComputeTarget>(`/api/infrastructure/${id}`),

  listWorkloads: () => apiFetch<WorkloadListItem[]>("/api/workloads"),
  getWorkload: (id: string) => apiFetch<Workload>(`/api/workloads/${id}`),

  analyze: (
    workloadId: string,
    imported?: { targets: ComputeTarget[]; evidence: PerformanceEvidence[] }
  ) =>
    apiFetch<DecisionRecord>("/api/analyze", {
      method: "POST",
      body: JSON.stringify({
        workload_id: workloadId,
        imported_targets: imported?.targets ?? [],
        imported_evidence: imported?.evidence ?? [],
      } satisfies AnalyzeRequestBody),
    }),

  getRecommendation: (id: string) => apiFetch<DecisionRecord>(`/api/recommendations/${id}`),

  /** Validates an uploaded record against the real schema
   * (docs/importing-results.md) — the backend is the single source of
   * truth for what's valid; nothing here re-implements validation. */
  validatePerformanceEvidence: (payload: unknown) =>
    apiFetch<PerformanceEvidence>("/api/import/performance-evidence", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  validateComputeTarget: (payload: unknown) =>
    apiFetch<ComputeTarget>("/api/import/compute-target", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listScenarios: () => apiFetch<ScenarioCatalogEntry[]>("/api/scenarios"),

  applyScenario: (workloadId: string, scenario: ScenarioType) =>
    apiFetch<ScenarioComparison>(`/api/workloads/${workloadId}/scenario`, {
      method: "POST",
      body: JSON.stringify({ scenario }),
    }),
};
