import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { useMemory, useMemoryMutations } from "@/api/hooks/skills";
import type { MemoryEntry } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Badge, EmptyState, Skeleton } from "@/components/ui/misc";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

const KINDS = ["rationale", "business_need", "human_procedure", "technical_note", "integration_note", "data_note", "decision", "lesson_learned"];

export default function MemoryTab({ skillId }: { skillId: string }) {
  const { t, i18n } = useTranslation(["skills", "common"]);
  const [showAll, setShowAll] = useState(false);
  const entries = useMemory(skillId, showAll ? "all" : "active");
  const { create, supersede, setStatus } = useMemoryMutations(skillId);
  const [dialog, setDialog] = useState<{ mode: "create" } | { mode: "edit"; entry: MemoryEntry } | null>(null);
  const [form, setForm] = useState({ kind: "rationale", title: "", body: "", step_key: "" });
  const [filter, setFilter] = useState<string>("");

  const openCreate = () => { setForm({ kind: "rationale", title: "", body: "", step_key: "" }); setDialog({ mode: "create" }); };
  const openEdit = (entry: MemoryEntry) => { setForm({ kind: entry.kind, title: entry.title, body: entry.body, step_key: entry.step_key ?? "" }); setDialog({ mode: "edit", entry }); };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!dialog) return;
    const done = () => setDialog(null);
    if (dialog.mode === "create") create.mutate({ kind: form.kind, title: form.title, body: form.body, step_key: form.step_key || null }, { onSuccess: done });
    else supersede.mutate({ id: dialog.entry.id, title: form.title, body: form.body }, { onSuccess: done });
  };
  const visible = (entries.data ?? []).filter((e) => !filter || e.kind === filter);
  const grouped = KINDS.map((k) => [k, visible.filter((e) => e.kind === k)] as const).filter(([, list]) => list.length);

  return (
    <>
      <Card>
        <CardHeader
          title={t("skills:memory.title")}
          description={t("skills:memory.subtitle")}
          actions={
            <div className="flex gap-2">
              <Select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-44">
                <option value="">{t("skills:memory.kind")}</option>
                {KINDS.map((k) => <option key={k} value={k}>{t(`skills:memory.kinds.${k}`)}</option>)}
              </Select>
              <Button variant="outline" onClick={() => setShowAll(!showAll)}>{showAll ? t("skills:memory.showActive") : t("skills:memory.showAll")}</Button>
              <Button onClick={openCreate}><Plus className="h-4 w-4" />{t("skills:memory.add")}</Button>
            </div>
          }
        />
        <CardBody className="space-y-6">
          {entries.isLoading && <Skeleton className="h-24" />}
          {entries.data && visible.length === 0 && <EmptyState title={t("skills:memory.empty")} />}
          {grouped.map(([kind, list]) => (
            <div key={kind}>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t(`skills:memory.kinds.${kind}`)}</h4>
              <ul className="space-y-2">
                {list.map((e) => (
                  <li key={e.id} className={cn("rounded-lg border border-border p-3", e.status !== "active" && "opacity-60")}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{e.title}</span>
                      {e.step_key && <Badge tone="primary">{e.step_key}</Badge>}
                      <Badge>{t(`skills:memory.source.${e.source}`, { defaultValue: e.source })}</Badge>
                      {e.status !== "active" && <Badge tone="warning">{t(`skills:memory.status.${e.status}`)}</Badge>}
                      <span className="ml-auto text-xs text-muted">{timeAgo(e.created_at, i18n.language)}</span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-muted">{e.body}</p>
                    {e.status === "active" && (
                      <div className="mt-2 flex gap-2">
                        <Button size="sm" variant="ghost" onClick={() => openEdit(e)}>{t("skills:memory.supersede")}</Button>
                        <Button size="sm" variant="ghost" onClick={() => setStatus.mutate({ id: e.id, status: "archived" })}>{t("skills:memory.archive")}</Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </CardBody>
      </Card>
      <Dialog open={!!dialog} onClose={() => setDialog(null)} title={dialog?.mode === "edit" ? t("skills:memory.supersede") : t("skills:memory.add")} footer={<><Button variant="outline" onClick={() => setDialog(null)}>{t("common:actions.cancel")}</Button><Button form="memory-form" type="submit" loading={create.isPending || supersede.isPending}>{t("common:actions.save")}</Button></>}>
        <form id="memory-form" className="space-y-3" onSubmit={submit}>
          {dialog?.mode === "create" && (
            <Field label={t("skills:memory.kind")}>
              <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{t(`skills:memory.kinds.${k}`)}</option>)}</Select>
            </Field>
          )}
          <Field label={t("skills:memory.titleField")}><Input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label={t("skills:memory.body")}><Textarea required rows={5} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></Field>
          {dialog?.mode === "create" && <Field label={t("skills:memory.step")}><Input value={form.step_key} onChange={(e) => setForm({ ...form, step_key: e.target.value })} /></Field>}
        </form>
      </Dialog>
    </>
  );
}
