// Mirrors api/app/models.py by hand. Keep the two in sync when either changes.

export type Provenance = "MEASURED" | "PUBLISHED" | "MODELED";
export type WorkloadClass = "realtime-inference" | "batch-inference" | "training";
export type ScenarioType =
  | "normal"
  | "demand_spike"
  | "h100_capacity_loss"
  | "cost_priority"
  | "performance_priority"
  | "strict_confidence_policy";

export interface Metric {
  value: number;
  confidence: number;
  provenance: Provenance;
  range_low: number | null;
  range_high: number | null;
  source: string;
  /** Traceable pointer back to the PerformanceEvidence this metric was
   * selected from (docs/decision-engine.md) — a benchmark_run_id for a
   * real measured run, or a synthetic fixture-evidence descriptor
   * otherwise. null for metrics outside the evidence-selection path
   * (e.g. ComputeTarget.price_per_hr_per_unit). */
  evidence_reference: string | null;
}

/** @deprecated use Metric */
export type PriceInfo = Metric;

export interface UnsupportedWorkloadClass {
  workload_class: string;
  reason: string;
}

export interface ComputeTarget {
  schema_version: "forgeway/v0.1";
  id: string;
  vendor: string;
  model: string;
  tier: "datacenter" | "edge" | "lab";
  location: string;
  architecture: string;
  memory_gb_per_device: number;
  interconnect: string;
  supported_precisions: string[];
  capacity_units_total: number;
  capacity_units_allocated: number;
  /** Structured runtime/framework qualification (e.g. "vLLM"). null means
   * "not known" — not populated by today's fixtures or the NVIDIA
   * discovery adapter; see docs/schemas.md. */
  runtime_support: string[] | null;
  price_per_hr_per_unit: PriceInfo;
  status: "healthy" | "degraded" | "offline";
  unsupported_workload_classes: UnsupportedWorkloadClass[];
  notes: string;
  /** Live discovery telemetry (docs/discovery.md) — distinct from
   * capacity_units_allocated/utilization_pct below, which are Forgeway's
   * own placement-bookkeeping concept. null for every fixture-sourced
   * target. */
  observed_gpu_utilization_pct: number | null;
  observed_memory_utilization_pct: number | null;
  /** ISO 8601 timestamp; null for fixture-sourced targets. */
  discovered_at: string | null;
  free_capacity_units: number;
  utilization_pct: number;
  /** Vendor-neutral alias for capacity_units_total. */
  accelerator_count: number;
}

export interface SLO {
  p99_latency_ms: number;
  min_throughput_tokens_per_s: number;
  availability_pct: number;
}

export interface Policy {
  allowed_vendors: string[];
  denied_vendors: string[];
  allowed_regions: string[];
  budget_ceiling_per_hr: number;
}

export interface CurrentPlacement {
  target_id: string;
  replica_count: number;
  measured_p99_latency_ms: number;
  measured_throughput_tokens_per_s_per_replica: number;
  cost_per_hr: number;
  provenance: Provenance;
  source: string;
}

export interface ObjectiveWeights {
  cost: number;
  performance: number;
  headroom: number;
}

export interface Workload {
  id: string;
  name: string;
  model_family: string;
  model_params_billion: number;
  workload_class: WorkloadClass;
  precision: string;
  weights_footprint_gb: number;
  kv_cache_overhead_gb: number;
  baseline_concurrency: number;
  slo: SLO;
  policy: Policy;
  current_placement: CurrentPlacement;
  objective_weights: ObjectiveWeights;
  min_confidence_pct: number;
  reanalyze: boolean;
}

export interface WorkloadListItem {
  workload: Workload;
  slo_status: "met" | "violated";
  latest_recommendation_id: string | null;
}

export interface FeasibilityCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface PredictedOutcome {
  replica_count: number;
  throughput_tokens_per_s_total: number;
  p99_latency_ms: number;
  cost_per_hr: number;
  meets_slo: boolean;
  provenance: Provenance;
}

export interface Prediction {
  target_id: string;
  workload_id: string;
  latency_p99_ms: Metric;
  throughput_tokens_per_s: Metric;
  cost_per_hr: Metric;
}

export interface NormalizedScores {
  cost: number;
  performance: number;
  headroom: number;
}

export type CandidateStatus = "recommended" | "feasible" | "rejected";

export interface CandidateEvaluation {
  target_id: string;
  target_label: string;
  vendor: string;
  feasible: boolean;
  status: CandidateStatus;
  checks: FeasibilityCheck[];
  rejection_reason: string | null;
  rejection_reasons: string[];
  raw_prediction: Prediction | null;
  slo_violations: string[];
  predicted: PredictedOutcome | null;
  capacity_constrained: boolean;
  capacity_note: string | null;
  normalized_scores: NormalizedScores | null;
  score: number | null;
  weighted_score: number | null;
  confidence_pct: number | null;
  meets_confidence_requirement: boolean | null;
  rank: number | null;
  why_not_chosen: string | null;
}

export interface EvidenceItem {
  label: string;
  display_value: string;
  metric: Metric;
  source: string;
}

export interface SplitAllocation {
  target_id: string;
  target_label: string;
  replica_count: number;
  throughput_tokens_per_s: number;
  throughput_share_pct: number;
  cost_per_hr: number;
  p99_latency_ms: number;
}

export interface UnmitigatedProjection {
  target_id: string;
  target_label: string;
  replica_count: number;
  required_throughput_tokens_per_s: number;
  available_throughput_tokens_per_s: number;
  utilization_ratio: number;
  predicted_p99_latency_ms: number;
  slo_violated: boolean;
  narrative: string;
}

export interface ScenarioParams {
  type: ScenarioType;
  demand_multiplier: number | null;
  capacity_loss_target_id: string | null;
  capacity_loss_pct: number | null;
  label: string;
}

export interface DecisionRecord {
  id: string;
  workload_id: string;
  workload_name: string;
  generated_at: string;
  scenario: ScenarioParams;
  derived_from_id: string | null;
  slo: SLO;
  current_placement: CurrentPlacement;
  effective_min_throughput_tokens_per_s: number;
  objective_weights: ObjectiveWeights;
  min_confidence_pct: number;
  candidates: CandidateEvaluation[];
  recommended_target_id: string | null;
  recommended: PredictedOutcome | null;
  split_allocation: SplitAllocation[];
  achieved_throughput_tokens_per_s: number;
  shortfall_tokens_per_s: number;
  slo_met: boolean;
  confidence_pct: number;
  evidence: EvidenceItem[];
  unmitigated_projection: UnmitigatedProjection | null;
  reasoning: string;
}

export interface ScenarioCatalogEntry {
  name: ScenarioType;
  label: string;
  description: string;
}

export interface ScenarioEventInfo {
  name: ScenarioType;
  label: string;
  description: string;
}

export interface ScenarioComparison {
  workload_id: string;
  event: ScenarioEventInfo;
  before: DecisionRecord;
  after: DecisionRecord;
  change_explanation: string;
}

export interface VendorBreakdown {
  vendor: string;
  devices_total: number;
  devices_allocated: number;
  utilization_pct: number;
}

export interface InsightCard {
  workload_id: string;
  workload_name: string;
  title: string;
  body: string;
  recommendation_id: string;
  current_target_id: string;
  current_cost_per_hr: number;
  recommended_target_id: string;
  recommended_cost_per_hr: number;
  savings_pct: number;
  slo_met: boolean;
  confidence_pct: number;
}

export interface EstateSummary {
  devices_total: number;
  devices_allocated: number;
  overall_utilization_pct: number;
  active_workloads: number;
  estimated_spend_per_hr: number;
  slo_compliance_pct: number;
  vendor_breakdown: VendorBreakdown[];
  insights: InsightCard[];
}

/** Mirrors api/app/core/schemas/performance_evidence.py — see
 * docs/importing-results.md for the "Import benchmark result" flow this
 * type supports. */
export interface PerformanceEvidence {
  schema_version: "forgeway/v0.1";
  compute_target_id: string;
  workload_id: string;
  configuration: string | null;
  metrics: Record<string, Metric>;
  provenance: Provenance;
  confidence: number;
  source: string;
  timestamp: string | null;
  forgeway_version: string;
  benchmark_run_id: string | null;
}

/** Sent with an /api/analyze request, never persisted server-side — the
 * browser (lib/imported-storage.ts) is the only place this data lives
 * between requests. Kept strictly additive to the reference fixture
 * catalog; the backend rejects an imported target id that collides with
 * one already in that catalog rather than silently merging them. */
export interface AnalyzeRequestBody {
  workload_id: string;
  objective_weights?: ObjectiveWeights;
  min_confidence_pct?: number;
  imported_targets?: ComputeTarget[];
  imported_evidence?: PerformanceEvidence[];
}
