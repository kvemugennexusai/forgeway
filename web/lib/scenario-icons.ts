import { DollarSign, Gauge, RotateCcw, ServerCrash, ShieldAlert, TrendingUp, type LucideIcon } from "lucide-react";

import type { ScenarioType } from "./types";

export const SCENARIO_ICON: Record<ScenarioType, LucideIcon> = {
  normal: RotateCcw,
  demand_spike: TrendingUp,
  h100_capacity_loss: ServerCrash,
  cost_priority: DollarSign,
  performance_priority: Gauge,
  strict_confidence_policy: ShieldAlert,
};
