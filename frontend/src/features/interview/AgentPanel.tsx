import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { Check, Copy, Laptop, Search } from "lucide-react";
import { api } from "@/api/client";
import type { InterviewDetail } from "@/api/types";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge, ErrorState } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";

interface Handoff {
  session_token: string;
  instruction: string;
}

/** Attaching an agent does not move the interview: AutoSkill keeps leading and the person keeps
 *  answering here. The agent only answers what can be observed on the machine. */
export function AgentPanel({ sessionId, detail }: { sessionId: string; detail: InterviewDetail }) {
  const { t } = useTranslation(["skills", "common"]);
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [copied, setCopied] = useState(false);
  const attach = useMutation({
    mutationFn: () => api<Handoff>(`/interviews/${sessionId}/handoff`, { method: "POST" }),
    onSuccess: setHandoff,
  });

  const live = detail.session.agent_live;
  const question = detail.session.pending_question;
  const waitingOnAgent = question?.audience === "agent" && detail.waiting_for === "answer";

  const copy = async () => {
    if (!handoff) return;
    await navigator.clipboard.writeText(handoff.instruction);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card>
      <CardHeader
        title={t("skills:agent.title")}
        description={t("skills:agent.description")}
        actions={live ? <Badge tone="success">{t("skills:agent.live")}</Badge> : undefined}
      />
      <CardBody className="space-y-3 text-sm">
        {waitingOnAgent && (
          <div className="rounded-xl border border-primary/40 bg-primary/5 p-3">
            <p className="flex items-center gap-2 font-medium">
              <Search className="h-4 w-4 text-primary" aria-hidden />
              {t("skills:agent.looking")}
            </p>
            <p className="mt-1 text-muted">{question?.question}</p>
            {!live && <p className="mt-2 text-xs text-warning">{t("skills:agent.notListening")}</p>}
          </div>
        )}
        {!handoff && (
          <>
            <p className="text-muted">{t("skills:agent.help")}</p>
            <Button size="sm" variant="outline" onClick={() => attach.mutate()} loading={attach.isPending}>
              <Laptop className="h-4 w-4" aria-hidden />
              {t("skills:agent.attach")}
            </Button>
          </>
        )}
        {handoff && (
          <div className="space-y-2">
            <p className="text-muted">{t("skills:agent.paste")}</p>
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-accent p-2 text-xs">
              {handoff.instruction}
            </pre>
            <Button size="sm" variant="outline" onClick={copy}>
              {copied ? <Check className="h-4 w-4 text-success" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
              {t(copied ? "common:actions.copied" : "common:actions.copy")}
            </Button>
            {/* the person is entrusting parts of their machine to the application: say so plainly */}
            <p className="text-xs text-muted">{t("skills:agent.privacy")}</p>
          </div>
        )}
        {attach.isError && <ErrorState message={errorMessage(attach.error, t)} />}
      </CardBody>
    </Card>
  );
}
