import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Cpu, Plug, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useLlmSwitch, useLlmSwitchMutations, type ProviderFields } from "@/api/hooks/llmswitch";
import type { LlmSwitchModel, LlmSwitchModels, LlmSwitchProvider, LlmSwitchState, LlmSwitchSubscription, LlmSwitchType } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Badge, EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { errorMessage } from "@/lib/errors";

type Form = { id?: string; type: string; name: string; base_url: string; model: string; api_key: string };
const empty: Form = { type: "lmstudio", name: "", base_url: "", model: "", api_key: "" };

/** Four ways of paying for a model, and the form differs for each. */
const FAMILIES = ["local", "api", "subscription", "cli"] as const;
type Family = (typeof FAMILIES)[number];

function familyOf(auth: string): Family {
  if (auth === "none") return "local";
  if (auth === "cli") return "cli";
  if (auth === "oauth") return "subscription";
  return "api";
}

const wantsKey = (auth: string) => auth === "api_key" || auth === "either";
/** 44 px of target under the thumb, the compact row back on a pointer screen. */
const touch = "h-11 sm:h-8";

export function LlmSwitchCard() {
  const { t } = useTranslation(["admin", "common"]);
  const { t: tc } = useTranslation("common");
  const state = useLlmSwitch();
  const { create, update, remove, assign, test, models, probeModels, reload } = useLlmSwitchMutations();
  const [form, setForm] = useState<Form | null>(null);
  const [choices, setChoices] = useState<LlmSwitchModel[]>([]);
  const [choicesError, setChoicesError] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);

  if (state.isLoading) {
    return (
      <Card className="mb-4">
        <CardHeader title={t("admin:llmswitch.title")} />
        <CardBody>
          <Skeleton className="h-32" />
        </CardBody>
      </Card>
    );
  }
  if (state.error || !state.data) {
    return (
      <Card className="mb-4">
        <CardHeader title={t("admin:llmswitch.title")} />
        <CardBody>
          <ErrorState message={errorMessage(state.error, tc)} onRetry={() => state.refetch()} retryLabel={tc("actions.retry")} />
        </CardBody>
      </Card>
    );
  }
  const data = state.data;

  if (!data.available) {
    return (
      <Card className="mb-4">
        <CardHeader title={t("admin:llmswitch.title")} description={t("admin:llmswitch.subtitle")} />
        <CardBody>
          <EmptyState title={t("admin:llmswitch.unavailable")} description={data.reason || t("admin:llmswitch.unavailableHint")} />
        </CardBody>
      </Card>
    );
  }

  const byId = (id: string) => data.providers.find((p) => p.id === id);
  const typeOf = (type: string): LlmSwitchType | undefined => data.types.find((x) => x.type === type);
  const usedFor = (id: string) => data.consumers.filter((c) => data.assignments[c] === id);

  const openNew = () => {
    setChoices([]);
    setChoicesError("");
    setForm(empty);
  };
  const openEdit = (p: LlmSwitchProvider) => {
    setChoices([]);
    setChoicesError("");
    setForm({ id: p.id, type: p.type, name: p.name, base_url: p.base_url, model: p.model, api_key: "" });
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const done = () => setForm(null);
    const fail = (err: unknown) => toast.error(errorMessage(err, tc));
    if (form.id) {
      const body: ProviderFields & { id: string } = { id: form.id, name: form.name, base_url: form.base_url, model: form.model };
      // An untouched key field must leave the stored key where it is.
      if (form.api_key) body.api_key = form.api_key;
      update.mutate(body, { onSuccess: done, onError: fail });
    } else {
      create.mutate(
        { type: form.type, name: form.name || undefined, base_url: form.base_url || undefined, model: form.model || undefined, api_key: form.api_key || undefined },
        { onSuccess: done, onError: fail },
      );
    }
  };

  const loadModels = () => {
    if (!form) return;
    setChoicesError("");
    const onResult = {
      onSuccess: (res: LlmSwitchModels) => {
        setChoices(res.models);
        setChoicesError(res.error || (res.models.length === 0 ? t("admin:llmswitch.noModels") : ""));
      },
      onError: (err: unknown) => setChoicesError(errorMessage(err, tc)),
    };
    // A saved provider is asked by id; a new one is asked from the address and key just typed, so the
    // list is there before the provider exists to point at.
    if (form.id) models.mutate({ id: form.id, refresh: true }, onResult);
    else probeModels.mutate({ type: form.type, base_url: form.base_url || undefined, api_key: form.api_key || undefined }, onResult);
  };

  const runTest = (id: string) =>
    test.mutate(id, {
      onSuccess: (r) =>
        r.ok
          ? toast.success(t("admin:llmswitch.testOk", { models: r.models }))
          : toast.error(t("admin:llmswitch.testFail", { message: r.error })),
      onError: (err) => toast.error(errorMessage(err, tc)),
    });

  const askRemove = (id: string) => {
    if (confirmId !== id) {
      setConfirmId(id);
      return;
    }
    setConfirmId(null);
    remove.mutate(id, { onError: (err) => toast.error(errorMessage(err, tc)) });
  };

  const formType = form ? typeOf(form.type) : undefined;

  return (
    <>
      <Card className="mb-4">
        <CardHeader
          title={t("admin:llmswitch.title")}
          description={t("admin:llmswitch.subtitle")}
          actions={
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" loading={reload.isPending} onClick={() => reload.mutate()}>
                <RefreshCw className="h-4 w-4" />
                <span className="sr-only sm:not-sr-only">{tc("actions.refresh")}</span>
              </Button>
              <Button onClick={openNew}>
                <Plus className="h-4 w-4" />
                {t("admin:llmswitch.add")}
              </Button>
            </div>
          }
        />
        <CardBody className="space-y-6">
          <p className="text-xs text-muted">
            {t("admin:llmswitch.registry", { path: data.registry_path })} · llmswitch {data.version}
            {!data.loads_models && ` · ${t("admin:llmswitch.loadsModelsOff")}`}
          </p>

          <section className="space-y-3">
            <h4 className="text-sm font-semibold">{t("admin:llmswitch.assignments")}</h4>
            <p className="text-sm text-muted">{t("admin:llmswitch.assignmentsHint")}</p>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {data.consumers.map((consumer) => (
                <Field key={consumer} label={t(`admin:llmswitch.purposes.${consumer}`)}>
                  <Select
                    className="h-11"
                    value={data.assignments[consumer] ?? ""}
                    disabled={data.providers.length === 0}
                    onChange={(e) =>
                      assign.mutate(
                        { purpose: consumer, provider: e.target.value || null },
                        { onError: (err) => toast.error(errorMessage(err, tc)) },
                      )
                    }
                  >
                    <option value="">{t("admin:llmswitch.none")}</option>
                    {data.providers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                        {p.model ? ` · ${p.model}` : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <h4 className="text-sm font-semibold">{t("admin:llmswitch.configured")}</h4>
            {data.providers.length === 0 ? (
              <EmptyState title={t("admin:llmswitch.empty")} description={t("admin:llmswitch.emptyHint")} />
            ) : (
              <ul className="divide-y divide-border">
                {data.providers.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-start gap-3 py-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">
                        {p.name}
                        {p.model && <span className="text-muted"> · {p.model}</span>}
                      </p>
                      <p className="truncate text-xs text-muted">
                        {p.label}
                        {p.base_url && ` · ${p.base_url}`}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {usedFor(p.id).map((c) => (
                          <Badge key={c} tone="primary">
                            {t(`admin:llmswitch.purposes.${c}`)}
                          </Badge>
                        ))}
                        {p.local && <Badge>{t("admin:llmswitch.local")}</Badge>}
                        {!p.realtime && <Badge tone="warning">{t("admin:llmswitch.deferred")}</Badge>}
                        {p.oauth_connected && <Badge tone="success">{t("admin:llmswitch.connected")}</Badge>}
                        {wantsKey(p.auth) &&
                          (p.has_key ? (
                            <Badge tone="success">{t("admin:llmswitch.apiKeySet")}</Badge>
                          ) : (
                            <Badge tone="danger">{t("admin:llmswitch.apiKeyMissing")}</Badge>
                          ))}
                      </div>
                    </div>
                    <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                      <Button
                        size="sm"
                        variant="outline"
                        className={touch}
                        loading={test.isPending && test.variables === p.id}
                        onClick={() => runTest(p.id)}
                      >
                        <Plug className="h-3.5 w-3.5" />
                        {t("admin:llmswitch.test")}
                      </Button>
                      <Button size="sm" variant="ghost" className={touch} onClick={() => openEdit(p)}>
                        {tc("actions.edit")}
                      </Button>
                      <Button
                        size="sm"
                        variant={confirmId === p.id ? "danger" : "ghost"}
                        className={touch}
                        onClick={() => askRemove(p.id)}
                      >
                        {confirmId === p.id ? tc("actions.confirm") : <Trash2 className="h-4 w-4 text-danger" />}
                        <span className="sr-only">{tc("actions.delete")}</span>
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <Subscriptions data={data} />
        </CardBody>
      </Card>

      <Dialog
        open={!!form}
        onClose={() => setForm(null)}
        title={form?.id ? t("admin:llmswitch.edit") : t("admin:llmswitch.add")}
        footer={
          <>
            <Button variant="outline" onClick={() => setForm(null)}>
              {tc("actions.cancel")}
            </Button>
            <Button form="llmswitch-form" type="submit" loading={create.isPending || update.isPending}>
              {tc("actions.save")}
            </Button>
          </>
        }
      >
        {form && (
          <form id="llmswitch-form" className="max-h-[65vh] space-y-3 overflow-y-auto pr-1" onSubmit={submit}>
            <Field label={t("admin:llmswitch.type")}>
              <Select
                className="h-11"
                disabled={!!form.id}
                value={form.type}
                onChange={(e) => {
                  const next = typeOf(e.target.value);
                  setChoices([]);
                  setChoicesError("");
                  setForm({ ...form, type: e.target.value, base_url: next?.base_url ?? "" });
                }}
              >
                {FAMILIES.map((family) => {
                  const options = data.types.filter((x) => familyOf(x.auth) === family);
                  if (options.length === 0) return null;
                  return (
                    <optgroup key={family} label={t(`admin:llmswitch.families.${family}`)}>
                      {options.map((x) => (
                        <option key={x.type} value={x.type}>
                          {x.label}
                        </option>
                      ))}
                    </optgroup>
                  );
                })}
              </Select>
            </Field>
            {formType?.note && <p className="text-xs text-muted">{formType.note}</p>}

            <Field label={t("admin:llmswitch.name")} hint={t("admin:llmswitch.nameHint")}>
              <Input className="h-11" value={form.name} placeholder={formType?.label} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>

            {formType?.auth !== "cli" && (
              <Field label={t("admin:llmswitch.baseUrl")} hint={t("admin:llmswitch.baseUrlHint")}>
                <Input
                  className="h-11"
                  value={form.base_url}
                  placeholder={formType?.base_url || "https://…/v1"}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                />
              </Field>
            )}

            {wantsKey(formType?.auth ?? "api_key") && (
              <Field
                label={t("admin:llmswitch.apiKey")}
                hint={form.id && byId(form.id)?.has_key ? t("admin:llmswitch.apiKeyKeep") : t("admin:llmswitch.apiKeyHint")}
              >
                <Input
                  className="h-11"
                  type="password"
                  autoComplete="off"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                />
              </Field>
            )}

            <Field label={t("admin:llmswitch.model")} hint={t(form.id ? "admin:llmswitch.modelHint" : "admin:llmswitch.modelHintNew")}>
              <div className="flex flex-wrap gap-2">
                <Input className="h-11 flex-1" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
                {/* Usable before Save: a new provider is probed from the address and key just
                    typed. Never disabled — a provider that needs an address it does not have yet
                    answers with the reason, which is more useful than a greyed-out button. */}
                <Button
                  type="button"
                  variant="outline"
                  className="h-11"
                  loading={models.isPending || probeModels.isPending}
                  onClick={loadModels}
                >
                  <Cpu className="h-4 w-4" />
                  {t("admin:llmswitch.loadModels")}
                </Button>
              </div>
            </Field>
            {choices.length > 0 && (
              <Select className="h-11" value="" onChange={(e) => e.target.value && setForm({ ...form, model: e.target.value })}>
                <option value="">{t("admin:llmswitch.pickModel")}</option>
                {choices.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {m.loaded ? ` — ${t("admin:llmswitch.inMemory")}` : ""}
                  </option>
                ))}
              </Select>
            )}
            {choicesError && <p className="text-xs text-danger">{choicesError}</p>}
          </form>
        )}
      </Dialog>
    </>
  );
}

function Subscriptions({ data }: { data: LlmSwitchState }) {
  const { t } = useTranslation("admin");
  if (data.subscriptions.length === 0) return null;
  const tone = (s: LlmSwitchSubscription): "success" | "danger" | "warning" | "neutral" =>
    s.utilizzabile ? "success" : s.impedimento ? "danger" : s.collegato ? "warning" : "neutral";
  const label = (s: LlmSwitchSubscription) =>
    s.utilizzabile ? t("llmswitch.status.ready") : s.impedimento ? t("llmswitch.status.blocked") : s.collegato ? t("llmswitch.status.expiring") : t("llmswitch.status.disconnected");
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold">{t("llmswitch.subscriptions")}</h4>
      <p className="text-sm text-muted">{t("llmswitch.subscriptionsHint")}</p>
      <ul className="divide-y divide-border">
        {data.subscriptions.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate">{s.label}</span>
            <Badge tone={tone(s)}>{label(s)}</Badge>
            {s.impedimento && <p className="w-full text-xs text-muted">{s.impedimento}</p>}
            {!s.collegato && s.come_accedere && (
              <code className="w-full break-all rounded bg-accent px-2 py-1 text-xs">
                {Array.isArray(s.come_accedere) ? s.come_accedere.join(" ") : s.come_accedere}
              </code>
            )}
          </li>
        ))}
      </ul>
      <p className="text-sm text-muted">
        {t("llmswitch.agents")}:{" "}
        {data.agents.length > 0 ? (
          <span className="inline-flex flex-wrap gap-1.5 align-middle">
            {data.agents.map((a) => (
              <Badge key={a} tone="success">
                {a}
              </Badge>
            ))}
          </span>
        ) : (
          t("llmswitch.agentsNone")
        )}
      </p>
    </section>
  );
}
