import { cn } from "@/lib/utils";

const VENDOR_LABEL: Record<string, string> = {
  nvidia: "NVIDIA",
  amd: "AMD",
  intel: "Intel",
  aws: "AWS",
};

const VENDOR_DOT: Record<string, string> = {
  nvidia: "bg-vendor-nvidia",
  amd: "bg-vendor-amd",
  intel: "bg-vendor-intel",
  aws: "bg-vendor-aws",
};

export function VendorBadge({ vendor, className }: { vendor: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", VENDOR_DOT[vendor] ?? "bg-muted-foreground")} />
      {VENDOR_LABEL[vendor] ?? vendor}
    </span>
  );
}
