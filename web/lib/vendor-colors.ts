// Keys match the CSS custom properties in app/globals.css (--vendor-*).
export const VENDOR_VAR: Record<string, string> = {
  nvidia: "--vendor-nvidia",
  amd: "--vendor-amd",
  intel: "--vendor-intel",
  aws: "--vendor-aws",
};

export function vendorColor(vendor: string): string {
  return `hsl(var(${VENDOR_VAR[vendor] ?? "--primary"}))`;
}

export function vendorFill(vendor: string, alpha: number): string {
  const varName = VENDOR_VAR[vendor] ?? "--primary";
  return `hsl(var(${varName}) / ${alpha})`;
}

export function vendorWash(vendor: string | null): string {
  const varName = vendor ? VENDOR_VAR[vendor] : undefined;
  const color = varName ? `var(${varName})` : "var(--primary)";
  return `radial-gradient(ellipse 640px 280px at 0% 0%, hsl(${color} / 0.14), transparent 65%)`;
}
