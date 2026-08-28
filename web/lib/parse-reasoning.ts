// The backend states cost savings in prose inside `reasoning` (see
// api/app/engine/decision.py) rather than as a separate field. Extracting it
// here surfaces a number the engine already computed — never a value the
// frontend invents — as a structured hero stat. Returns null on any shape
// that doesn't carry a savings figure, and the hero falls back to a plain
// cost stat in that case.
export function extractSavingsPct(reasoning: string): number | null {
  const match = reasoning.match(/(\d+(?:\.\d+)?)%\s+less than the current/);
  if (!match) return null;
  const pct = Number(match[1]);
  return Number.isFinite(pct) ? pct : null;
}
