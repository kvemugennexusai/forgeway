"""The compute-target schema — what a caller knows about one piece of
heterogeneous AI hardware, however it learned it (a static fixture today; a
live discovery adapter tomorrow)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from app.core.schemas.evidence import Metric


class UnsupportedWorkloadClass(BaseModel):
    workload_class: str
    reason: str


class ComputeTarget(BaseModel):
    id: str
    vendor: str
    model: str
    tier: Literal["datacenter", "edge", "lab"]
    location: str
    architecture: str
    memory_gb_per_device: float
    interconnect: str
    supported_precisions: list[str]
    capacity_units_total: int
    capacity_units_allocated: int
    price_per_hr_per_unit: Metric
    status: Literal["healthy", "degraded", "offline"]
    unsupported_workload_classes: list[UnsupportedWorkloadClass] = Field(default_factory=list)
    notes: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def free_capacity_units(self) -> int:
        return max(self.capacity_units_total - self.capacity_units_allocated, 0)

    @computed_field  # type: ignore[misc]
    @property
    def utilization_pct(self) -> float:
        if self.capacity_units_total == 0:
            return 0.0
        return round(100 * self.capacity_units_allocated / self.capacity_units_total, 1)
