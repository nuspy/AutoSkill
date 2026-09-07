import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

/** Minimal, dependency-free markdown renderer for previews (headings, lists, code, bold, links). */
function escape(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** For text going inside a quoted attribute, where `escape` alone is not enough: a quote in a
 *  translated label would close the attribute and put the rest of it into the markup. */
function attr(s: string) {
  return escape(s).replace(/"/g, "&quot;");
}

function inline(s: string) {
  return escape(s)
    .replace(/`([^`]+)`/g, '<code class="rounded bg-accent px-1 py-0.5 text-xs">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a class="text-primary underline" href="$2" target="_blank" rel="noreferrer">$1</a>');
}

export function toHtml(md: string, copyLabel = "Copy"): string {
  const lines = md.split("\n");
  const out: string[] = [];
  let inCode = false;
  let list: "ul" | "ol" | null = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of lines) {
    if (raw.startsWith("```")) {
      closeList();
      if (inCode) {
        out.push("</code></pre>", "</div>");
        inCode = false;
      } else {
        // The guide's commands used to be readable and untakeable: one button copied the whole
        // document, and the single line a person actually had to run had to be selected by hand.
        out.push(
          '<div class="relative group">',
          `<button type="button" data-copy aria-label="${attr(copyLabel)}" title="${attr(copyLabel)}" class="absolute right-2 top-2 rounded border border-border bg-card px-2 py-0.5 text-xs text-muted opacity-0 transition group-hover:opacity-100 focus:opacity-100">${escape(copyLabel)}</button>`,
          '<pre class="overflow-x-auto rounded-lg bg-accent p-3 pr-16 text-xs"><code>',
        );
        inCode = true;
      }
      continue;
    }
    if (inCode) { out.push(escape(raw)); continue; }
    if (/^<!--.*-->$/.test(raw.trim())) continue;
    const h = raw.match(/^(#{1,6})\s+(.*)$/);
    if (h) { closeList(); const level = h[1].length; out.push(`<h${level} class="${level <= 2 ? "mt-4 text-lg font-semibold" : "mt-3 font-semibold"}">${inline(h[2])}</h${level}>`); continue; }
    const ul = raw.match(/^\s*[-*]\s+(.*)$/);
    const ol = raw.match(/^\s*\d+\.\s+(.*)$/);
    if (ul || ol) {
      const kind = ul ? "ul" : "ol";
      if (list !== kind) { closeList(); list = kind; out.push(`<${kind} class="${kind === "ul" ? "list-disc" : "list-decimal"} pl-5 space-y-0.5">`); }
      out.push(`<li>${inline((ul ?? ol)![1])}</li>`);
      continue;
    }
    closeList();
    if (raw.startsWith(">")) { out.push(`<blockquote class="border-l-2 border-warning pl-3 text-muted">${inline(raw.slice(1).trim())}</blockquote>`); continue; }
    if (raw.trim() === "") { out.push(""); continue; }
    if (raw.startsWith("|")) { out.push(`<pre class="text-xs">${escape(raw)}</pre>`); continue; }
    out.push(`<p>${inline(raw)}</p>`);
  }
  closeList();
  if (inCode) out.push("</code></pre>", "</div>");
  return out.join("\n");
}

export function Markdown({ source, className }: { source: string; className?: string }) {
  const { t } = useTranslation(["common"]);
  const copyLabel = t("common:actions.copy");
  const html = useMemo(() => toHtml(source, copyLabel), [source, copyLabel]);
  // One delegated handler instead of a button per block: the markup is a string, so there is no React
  // element to hang an onClick on, and walking the DOM after every render to attach listeners would
  // be the same work done worse. The text is read from the block at click time rather than duplicated
  // into an attribute, so what gets copied is always exactly what is on screen.
  const onClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const button = (e.target as HTMLElement).closest("[data-copy]");
    if (!button) return;
    const code = button.parentElement?.querySelector("code")?.textContent ?? "";
    if (!code) return;
    navigator.clipboard.writeText(code);
    toast.success(t("common:actions.copied"));
  };
  return (
    <div
      className={`space-y-2 text-sm leading-relaxed ${className ?? ""}`}
      onClick={onClick}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
