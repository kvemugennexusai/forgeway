import { Badge } from "@/components/ui/badge";
import type { Provenance } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABEL: Record<Provenance, string> = {
  MEASURED: "Measured",
  PUBLISHED: "Published",
  MODELED: "Modeled",
};

const VARIANT: Record<Provenance, "measured" | "published" | "modeled"> = {
  MEASURED: "measured",
  PUBLISHED: "published",
  MODELED: "modeled",
};

export function ProvenanceBadge({
  provenance,
  className,
}: {
  provenance: Provenance;
  className?: string;
}) {
  return (
    <Badge variant={VARIANT[provenance]} className={cn("font-mono uppercase", className)}>
      {LABEL[provenance]}
    </Badge>
  );
}
