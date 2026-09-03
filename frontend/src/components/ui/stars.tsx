import { Star } from "lucide-react";
import { cn } from "@/lib/cn";

/** Read-only or interactive 1-5 stars. */
export function Stars({ value, count, onChange, size = "h-4 w-4" }: { value: number | null | undefined; count?: number; onChange?: (stars: number) => void; size?: string }) {
  const v = value ?? 0;
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={v ? `${v}/5` : "-"}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" disabled={!onChange} aria-label={`${n}`} className={cn("rounded", onChange ? "cursor-pointer hover:scale-110" : "cursor-default")} onClick={() => onChange?.(n)}>
          <Star className={cn(size, n <= Math.round(v) ? "fill-current text-warning" : "text-muted")} />
        </button>
      ))}
      {count !== undefined && <span className="ml-1 text-xs text-muted">{v ? v.toFixed(1) : "-"} ({count})</span>}
    </span>
  );
}
