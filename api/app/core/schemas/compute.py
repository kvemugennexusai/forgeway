"""The compute-target schema — what a caller knows about one piece of
heterogeneous AI hardware, however it learned it (a static fixture today; a
live discovery adapter tomorrow).

This is the forgeway/v0.1 ComputeTarget contract (see
docs/schemas.md and app.core.schemas.v0_1) defined in place, since it was
already this codebase's single canonical compute-target type — there was no
duplicated ad hoc structure to migrate away from."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field

from app.core.schemas.evidence import Metric

SCHEMA_VERSION = "forgeway/v0.1"


class UnsupportedWorkloadClass(BaseModel):
    workload_class: str
    reason: str


class ComputeTarget(BaseModel):
    schema_version: Literal["forgeway/v0.1"] = SCHEMA_VERSION
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
    # Structured runtime/framework qualification (e.g. "vLLM", "TensorRT-LLM").
    # None means "not known" — that's the honest state of every current
    # fixture, which only carries this information as free text inside
    # `unsupported_workload_classes[].reason`. An empty list is reserved for
    # "known: this target qualifies no runtimes", a distinct, stronger claim
    # nothing in this codebase can make yet. Left here, typed, so a future
    # discovery adapter or fixture update has somewhere to put it without
    # another schema change.
    runtime_support: Optional[list[str]] = None
    price_per_hr_per_unit: Metric
    status: Literal["healthy", "degraded", "offline"]
    unsupported_workload_classes: list[UnsupportedWorkloadClass] = Field(default_factory=list)
    notes: str = ""
    # Live discovery telemetry — deliberately separate from
    # capacity_units_allocated/utilization_pct above, which are Forgeway's
    # own placement-bookkeeping concept (how many capacity units *Forgeway*
    # has assigned to workloads), not instantaneous hardware busyness.
    # None for every fixture; populated by a discovery adapter
    # (app.discovery) when it actually queried the hardware.
    observed_gpu_utilization_pct: Optional[float] = None
    observed_memory_utilization_pct: Optional[float] = None
    discovered_at: Optional[datetime] = None

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

    @computed_field  # type: ignore[misc]
    @property
    def accelerator_count(self) -> int:
        """Vendor-neutral alias for capacity_units_total. In this fixture
        format one capacity unit is one physical accelerator; this property
        exists so a caller unfamiliar with "capacity units" as a term still
        has a name it recognizes, without duplicating the underlying data."""
        return self.capacity_units_total
