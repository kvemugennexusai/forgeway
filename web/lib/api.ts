import type {
  ComputeTarget,
  DecisionRecord,
  EstateSummary,
  ScenarioCatalogEntry,
  ScenarioComparison,
  ScenarioType,
  Workload,
  WorkloadListItem,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
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

  analyze: (workloadId: string) =>
    apiFetch<DecisionRecord>("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ workload_id: workloadId }),
    }),

  getRecommendation: (id: string) => apiFetch<DecisionRecord>(`/api/recommendations/${id}`),

  listScenarios: () => apiFetch<ScenarioCatalogEntry[]>("/api/scenarios"),

  applyScenario: (workloadId: string, scenario: ScenarioType) =>
    apiFetch<ScenarioComparison>(`/api/workloads/${workloadId}/scenario`, {
      method: "POST",
      body: JSON.stringify({ scenario }),
    }),
};
