import { useMemo } from "react";

/** Minimal, dependency-free markdown renderer for previews (headings, lists, code, bold, links). */
function escape(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inline(s: string) {
  return escape(s)
    .replace(/`([^`]+)`/g, '<code class="rounded bg-accent px-1 py-0.5 text-xs">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a class="text-primary underline" href="$2" target="_blank" rel="noreferrer">$1</a>');
}

export function toHtml(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];
  let inCode = false;
  let list: "ul" | "ol" | null = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of lines) {
    if (raw.startsWith("```")) {
      closeList();
      if (inCode) { out.push("</code></pre>"); inCode = false; } else { out.push('<pre class="overflow-x-auto rounded-lg bg-accent p-3 text-xs"><code>'); inCode = true; }
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
  if (inCode) out.push("</code></pre>");
  return out.join("\n");
}

export function Markdown({ source, className }: { source: string; className?: string }) {
  const html = useMemo(() => toHtml(source), [source]);
  return <div className={`space-y-2 text-sm leading-relaxed ${className ?? ""}`} dangerouslySetInnerHTML={{ __html: html }} />;
}
