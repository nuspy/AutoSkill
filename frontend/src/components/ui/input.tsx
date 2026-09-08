import {
  forwardRef,
  useEffect,
  useRef,
  type AnimationEvent,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";

const base =
  "w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-60";

// React tracks a controlled input's value with a private tracker whose stored value only updates when
// JS sets `.value`. Browser autofill sets it at the engine level, bypassing that, so the tracker still
// reads the old (empty) value and no `onChange` ever fires — the field looks filled but React state is
// blank, and the form submits nothing. Dispatching a native `input` event makes React's change plugin
// re-read the DOM, see the difference against its stale tracker, and fire `onChange` once, syncing the
// controlled value to what the browser wrote. It is a no-op when the value already matches.
function syncAutofill(el: HTMLInputElement | null): void {
  if (el && el.value) el.dispatchEvent(new Event("input", { bubbles: true }));
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, onAnimationStart, ...props }, ref) => {
    const inner = useRef<HTMLInputElement | null>(null);
    const setRef = (el: HTMLInputElement | null) => {
      inner.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    };
    // The `:-webkit-autofill` animation is the live signal; the mount check catches a browser that
    // filled the field before this listener was attached (a hard reload with saved credentials).
    useEffect(() => {
      const id = window.setTimeout(() => syncAutofill(inner.current), 120);
      return () => window.clearTimeout(id);
    }, []);
    const handleAnimationStart = (e: AnimationEvent<HTMLInputElement>) => {
      if (e.animationName === "onAutoFillStart") syncAutofill(e.currentTarget);
      onAnimationStart?.(e);
    };
    return <input ref={setRef} onAnimationStart={handleAnimationStart} className={cn(base, className)} {...props} />;
  },
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn(base, "min-h-24", className)} {...props} />,
);
Textarea.displayName = "Textarea";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => <select ref={ref} className={cn(base, className)} {...props} />,
);
Select.displayName = "Select";

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-fg">{label}</span>
      {children}
      {hint && !error && <span className="block text-xs text-muted">{hint}</span>}
      {error && <span className="block text-xs text-danger">{error}</span>}
    </label>
  );
}
