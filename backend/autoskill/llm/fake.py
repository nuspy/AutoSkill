# ruff: noqa: E501
"""Scripted provider for tests and `AUTOSKILL_LLM_FAKE=1` demos.

Responses are matched by `purpose` (and optionally by a substring of the last user message) in
order; unmatched calls return the default reply. Every call is recorded for assertions.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from autoskill.llm.provider import (
    Capabilities,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    Usage,
)


@dataclass
class Scripted:
    purpose: str | None = None
    contains: str | None = None
    text: str | None = None
    json: Any = None
    tool_calls: list[tuple[str, dict[str, Any]]] | None = None


class FakeLlmProvider:
    name = "fake"

    def __init__(self, scripts: list[Scripted] | None = None, default_json: Any = None) -> None:
        self.model = "fake-model"
        self.capabilities = Capabilities(tools=True, json_schema=True)
        self._scripts: deque[Scripted] = deque(scripts or [])
        self._default_json = default_json
        self.calls: list[ChatRequest] = []

    def script(self, *items: Scripted) -> None:
        self._scripts.extend(items)

    def _match(self, req: ChatRequest) -> Scripted | None:
        last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        for i, s in enumerate(self._scripts):
            if s.purpose and s.purpose != req.purpose:
                continue
            if s.contains and s.contains not in last_user:
                continue
            del self._scripts[i]
            return s
        return None

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.calls.append(req)
        s = self._match(req)
        usage = Usage(input_tokens=100, output_tokens=50)
        if s is None:
            content = json.dumps(self._default_json) if self._default_json is not None else "ok"
            return ChatResponse(message=ChatMessage(role="assistant", content=content), usage=usage)
        if s.tool_calls:
            calls = [ToolCall(id=f"call_{i}", name=n, arguments=a) for i, (n, a) in enumerate(s.tool_calls)]
            return ChatResponse(
                message=ChatMessage(role="assistant", content=s.text or "", tool_calls=calls), usage=usage
            )
        content = s.text if s.text is not None else json.dumps(s.json)
        return ChatResponse(message=ChatMessage(role="assistant", content=content), usage=usage)

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        res = await self.chat(req)
        for word in res.text.split(" "):
            yield ChatChunk(delta=word + " ")


# --- demo provider: canned structured answers per purpose, so the whole flow runs without an LLM -----

DEMO_KNOWLEDGE = {
    "task": {
        "name": "Invoice check",
        "goal": "Check supplier invoices against purchase orders every Monday and alert accounting.",
        "trigger": "Every Monday morning",
        "actor_role": "Accounts payable clerk",
    },
    "data_sources": [
        {
            "ref": "invoices",
            "kind": "spreadsheet",
            "role": "list of invoices to check",
            "access": "Shared drive, Invoices.xlsx",
            "fields_used": ["number", "amount", "supplier"],
            "sensitivity": "internal",
        },
        {
            "ref": "erp",
            "kind": "web_app",
            "role": "purchase orders",
            "access": "ERP web app, Orders module",
            "fields_used": ["po_number", "amount"],
            "sensitivity": "internal",
        },
    ],
    "inputs": [{"name": "Invoices.xlsx", "description": "this week's invoices", "example": "12 rows"}],
    "outputs": [{"name": "anomalies email", "description": "list of invoices over budget", "example": "3 invoices"}],
    "steps": [
        {
            "key": "open-sheet",
            "title": "Open the sheet",
            "description": "Open Invoices.xlsx and select the current month sheet.",
            "kind_hint": "deterministic",
            "uses": ["invoices"],
            "decision_rules": ["only rows with status 'new'"],
            "example": "12 rows in March",
            "side_effects": "read_only",
            "restore_strategy": "none",
        },
        {
            "key": "flag",
            "title": "Flag anomalies",
            "description": "Compare each amount with the purchase order in the ERP and flag rows over the order amount.",
            "kind_hint": "generative",
            "uses": ["invoices", "erp"],
            "decision_rules": ["over the PO amount by more than 5% -> flag"],
            "example": "A1: 1200 vs PO 1000 -> flagged",
            "side_effects": "reversible",
            "restore_strategy": "backup_file",
        },
        {
            "key": "send",
            "title": "Email accounting",
            "description": "Send the flagged list to accounting.",
            "kind_hint": "deterministic",
            "uses": [],
            "decision_rules": ["only if at least one row is flagged"],
            "example": "email with 3 rows",
            "side_effects": "irreversible",
            "restore_strategy": "none",
        },
    ],
    "edge_cases": [
        {
            "condition": "the sheet is empty",
            "expected_handling": "stop and tell the person",
            "source_ref": "invoices",
            "confirmed": True,
        },
        {
            "condition": "PO not found",
            "expected_handling": "flag the row as 'no PO'",
            "source_ref": "erp",
            "confirmed": True,
        },
    ],
    "acceptance_criteria": [
        {"id": "AC1", "statement": "every invoice over its PO by more than 5% is in the email", "checkable_by": "human"}
    ],
    "integrations": [
        {
            "system": "email",
            "purpose": "send the list",
            "protocol": "component:email-mcp",
            "credentials_needed": ["SMTP_PASSWORD"],
            "authorizations": "own mailbox",
            "contact": "",
        }
    ],
    "constraints": {
        "tools_available": ["spreadsheet", "ERP web app", "email"],
        "forbidden_actions": ["never pay anything"],
        "secrets_needed": ["SMTP_PASSWORD"],
        "pii": False,
    },
    "open_questions": [],
    "glossary": [{"name": "PO", "description": "purchase order", "example": "PO-2024-118"}],
    "human_confirmed": False,
}

DEMO_DRAFT = {
    "description": "Checks supplier invoices against purchase orders every Monday and emails accounting the anomalies. Use when the user asks to verify or flag invoices.",
    "overview": "# Invoice check\n\nVerifies this week's invoices against purchase orders and reports anomalies to accounting.\n\nInputs: the invoices spreadsheet. Output: an email with the flagged rows.",
    "steps": [
        {
            "key": "open-sheet",
            "title": "Open the sheet",
            "instruction": "Open Invoices.xlsx from the shared drive and select the current month sheet.",
            "kind": "deterministic",
            "side_effects": "read_only",
            "restore_strategy": "none",
            "data_source_refs": ["invoices"],
            "success_criteria": "the rows of the current month are listed",
        },
        {
            "key": "flag",
            "title": "Flag anomalies",
            "instruction": "For each row, look up the purchase order in the ERP and flag the row when the amount exceeds the order by more than 5%.",
            "kind": "generative",
            "side_effects": "reversible",
            "restore_strategy": "backup_file",
            "data_source_refs": ["invoices", "erp"],
            "success_criteria": "every row over its PO by more than 5% is flagged",
            "failure_modes": ["PO not found"],
        },
        {
            "key": "send",
            "title": "Email accounting",
            "instruction": "Send the flagged rows to accounting@example.com using the email component.",
            "kind": "deterministic",
            "side_effects": "irreversible",
            "restore_strategy": "none",
            "network": True,
            "success_criteria": "accounting received the list",
        },
    ],
    "edge_cases_markdown": "- If the sheet is empty, stop and tell the person.\n- If a PO is missing, flag the row as 'no PO'.",
    "files": [
        {"path": "references/columns.md", "content": "| number | amount | supplier | status |\n|---|---|---|---|"}
    ],
    "dependencies": [],
    "changelog": "first draft",
}


class DemoProvider(FakeLlmProvider):
    """Deterministic answers keyed by purpose: interviews complete in one turn, drafts have three steps,
    coach and analyst return fixed but well-formed structures. Enabled with AUTOSKILL_LLM_FAKE=demo."""

    name = "demo"

    def _demo(self, req: ChatRequest) -> Any:
        last = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        purpose = req.purpose or ""
        if purpose == "supervisor":
            return {"decision": "proceed", "reasons": ["all gates satisfied"], "missing": [], "confidence": 0.9}
        if purpose == "interviewer":
            if "ONE question" in last:
                return {
                    "question": "Is there anything else I should know?",
                    "why": "to be sure",
                    "expects": "text",
                    "options": [],
                    "target_gate": "G1",
                }
            if "memory" in last.lower() and "entries" in last.lower():
                return {
                    "entries": [
                        {
                            "kind": "rationale",
                            "title": "Why the 5% tolerance",
                            "body": "Small rounding differences are normal; only larger gaps matter.",
                        }
                    ]
                }
            if "summar" in last.lower() and "knowledge" in last.lower() and "json" not in last.lower()[:200]:
                return None  # plain text summary
            return DEMO_KNOWLEDGE
        if purpose == "author":
            if "tools" in last.lower() and "server" in last.lower():
                return {
                    "description": "Deterministic tools for the invoice check",
                    "tools": [
                        {
                            "name": "open_sheet",
                            "step_key": "open-sheet",
                            "description": "List the rows of the current month",
                            "params": [
                                {"name": "path", "type": "string", "description": "workbook path", "required": True}
                            ],
                            "returns": "rows",
                            "side_effects": "read_only",
                            "network": False,
                            "body": "    return {'rows': [], 'path': path}\n",
                        }
                    ],
                    "dependencies": [],
                    "env_requirements": [],
                }
            return DEMO_DRAFT
        if purpose == "coach":
            if "entries" in last.lower() and "memory" in last.lower():
                return {"entries": []}
            return {
                "reply": "Understood, I will keep it that way.",
                "no_change": True,
                "new_instruction": None,
                "change_summary": None,
                "memory_entries": [],
            }
        if purpose == "analyst":
            if "entries" in last.lower() and "memory" in last.lower():
                return {"entries": []}
            return {
                "hypotheses": ["amounts sometimes carry currency symbols"],
                "instructions": "strip currency symbols before comparing amounts",
                "rationale": "Three runs failed on the same parsing error.",
                "memory_entries": [],
            }
        return None

    async def chat(self, req: ChatRequest) -> ChatResponse:
        self.calls.append(req)
        s = self._match(req)
        if s is not None:
            self._scripts.appendleft(s)
            return await super().chat(req)
        usage = Usage(input_tokens=100, output_tokens=50)
        data = self._demo(req)
        if data is None:
            text = "I understood the task: every Monday, check invoices against purchase orders and email the anomalies to accounting."
            return ChatResponse(message=ChatMessage(role="assistant", content=text), usage=usage)
        return ChatResponse(message=ChatMessage(role="assistant", content=json.dumps(data)), usage=usage)
