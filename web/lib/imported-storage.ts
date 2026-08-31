// Browser-local storage for "Import benchmark result" (docs/importing-results.md).
//
// Deliberately the ONLY place this feature keeps state — there is no
// server-side persistence, no accounts, no database. Everything here lives
// in this browser, this device, until cleared. Every read/write is wrapped
// defensively: localStorage can throw (private browsing, disabled storage,
// quota limits) or simply not exist (server-side rendering), and none of
// that should ever crash the page — it should just behave as "nothing
// imported yet".

import type { ComputeTarget, PerformanceEvidence } from "./types";

const TARGETS_KEY = "forgeway.imported.targets";
const EVIDENCE_KEY = "forgeway.imported.evidence";

function readArray<T>(key: string): T[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function writeArray<T>(key: string, value: T[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage unavailable or full — the import silently doesn't persist
    // rather than crashing the page; the caller's own success/error UI
    // is driven by the backend validation call, not by this write.
  }
}

export function getImportedTargets(): ComputeTarget[] {
  return readArray<ComputeTarget>(TARGETS_KEY);
}

export function getImportedEvidence(): PerformanceEvidence[] {
  return readArray<PerformanceEvidence>(EVIDENCE_KEY);
}

/** Adds a target, replacing any existing entry with the same id — a
 * re-import (e.g. re-running `forgeway discover`) updates in place rather
 * than accumulating duplicates. */
export function addImportedTarget(target: ComputeTarget): void {
  const existing = getImportedTargets().filter((t) => t.id !== target.id);
  writeArray(TARGETS_KEY, [...existing, target]);
}

export function removeImportedTarget(id: string): void {
  writeArray(
    TARGETS_KEY,
    getImportedTargets().filter((t) => t.id !== id)
  );
}

function evidenceKey(e: PerformanceEvidence): string {
  return e.benchmark_run_id ?? `${e.compute_target_id}::${e.workload_id}`;
}

/** Adds an evidence record, replacing any existing entry with the same
 * benchmark_run_id (or the same target/workload pair, for evidence without
 * a run id) — same re-import-in-place behavior as addImportedTarget. */
export function addImportedEvidence(evidence: PerformanceEvidence): void {
  const key = evidenceKey(evidence);
  const existing = getImportedEvidence().filter((e) => evidenceKey(e) !== key);
  writeArray(EVIDENCE_KEY, [...existing, evidence]);
}

export function removeImportedEvidence(evidence: PerformanceEvidence): void {
  const key = evidenceKey(evidence);
  writeArray(
    EVIDENCE_KEY,
    getImportedEvidence().filter((e) => evidenceKey(e) !== key)
  );
}

export function clearImported(): void {
  writeArray(TARGETS_KEY, []);
  writeArray(EVIDENCE_KEY, []);
}

export function importedTargetIds(): Set<string> {
  return new Set(getImportedTargets().map((t) => t.id));
}
