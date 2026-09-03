"""Deterministic completeness gates over a KnowledgeDoc. Code decides; the supervisor only advises."""

from __future__ import annotations

from autoskill.schemas.knowledge import GateResult, KnowledgeDocModel

TABULAR_KINDS = {"spreadsheet", "database", "api", "file"}
VAGUE_MARKERS = ("it depends", "dipende", "sometimes", "a volte", "usually", "di solito", "maybe", "forse")


def compute_gates(doc: KnowledgeDocModel) -> list[GateResult]:
    gates: list[GateResult] = []

    goal_ok = bool(doc.task.goal.strip()) and bool(doc.task.trigger.strip())
    gates.append(
        GateResult(
            id="G1", title="Goal and trigger", passed=goal_ok, detail="" if goal_ok else "goal or trigger missing"
        )
    )

    source_names = {s.ref for s in doc.data_sources}
    problems: list[str] = []
    for step in doc.steps:
        for ref in step.uses:
            if ref not in source_names:
                problems.append(f"step {step.key} uses unknown source {ref!r}")
    for src in doc.data_sources:
        if not src.access.strip():
            problems.append(f"source {src.ref!r} has no access notes")
        if src.kind in TABULAR_KINDS and not src.fields_used:
            problems.append(f"source {src.ref!r} lists no fields")
    if not doc.data_sources:
        problems.append("no data source declared")
    gates.append(GateResult(id="G2", title="Data sources known", passed=not problems, detail="; ".join(problems[:3])))

    step_problems = []
    if len(doc.steps) < 2:
        step_problems.append("fewer than 2 steps")
    for step in doc.steps:
        if not step.description.strip():
            step_problems.append(f"step {step.key} has no description")
        if not step.example.strip():
            step_problems.append(f"step {step.key} has no example")
        if step.unclear:
            step_problems.append(f"step {step.key} marked unclear")
    gates.append(
        GateResult(
            id="G3",
            title="Steps described with examples",
            passed=not step_problems,
            detail="; ".join(step_problems[:3]),
        )
    )

    vague = []
    for step in doc.steps:
        text = " ".join([step.description, *step.decision_rules]).lower()
        if step.kind_hint == "generative" and not step.decision_rules:
            vague.append(f"step {step.key} has no decision rules")
        if any(marker in text for marker in VAGUE_MARKERS) and not step.decision_rules:
            vague.append(f"step {step.key} sounds vague")
    gates.append(GateResult(id="G4", title="Decision rules explicit", passed=not vague, detail="; ".join(vague[:3])))

    confirmed_by_source = {e.source_ref for e in doc.edge_cases if e.confirmed and e.source_ref}
    missing_ec = [s.ref for s in doc.data_sources if s.ref not in confirmed_by_source]
    any_confirmed = any(e.confirmed for e in doc.edge_cases)
    g5_ok = bool(doc.data_sources) and (not missing_ec or (any_confirmed and len(doc.data_sources) == 1))
    gates.append(
        GateResult(
            id="G5",
            title="Edge cases confirmed",
            passed=g5_ok,
            detail="" if g5_ok else f"no confirmed edge case for {missing_ec[:3]}",
        )
    )

    g6_ok = any(c.checkable_by in ("human", "both") for c in doc.acceptance_criteria)
    gates.append(
        GateResult(
            id="G6", title="Acceptance criteria", passed=g6_ok, detail="" if g6_ok else "no human-checkable criterion"
        )
    )

    gates.append(
        GateResult(
            id="G7", title="No open questions", passed=not doc.open_questions, detail="; ".join(doc.open_questions[:3])
        )
    )

    gates.append(
        GateResult(
            id="G8",
            title="Human confirmed summary",
            passed=doc.human_confirmed,
            detail="" if doc.human_confirmed else "waiting for confirmation",
        )
    )

    integ_problems = [i.system for i in doc.integrations if not i.credentials_needed and not i.authorizations]
    g9_ok = not integ_problems
    gates.append(
        GateResult(
            id="G9",
            title="Integrations documented",
            passed=g9_ok,
            detail="" if g9_ok else f"credentials/authorizations unknown for {integ_problems[:3]}",
        )
    )

    se_problems = [
        s.key
        for s in doc.steps
        if s.side_effects == "unknown" or (s.side_effects != "read_only" and s.restore_strategy == "unknown")
    ]
    gates.append(
        GateResult(
            id="G10",
            title="Side effects and reversibility",
            passed=not se_problems,
            detail="" if not se_problems else f"unknown for steps {se_problems[:3]}",
        )
    )
    return gates


def first_failing(gates: list[GateResult], skip: tuple[str, ...] = ("G8",)) -> GateResult | None:
    for g in gates:
        if not g.passed and g.id not in skip:
            return g
    return None


def all_passed(gates: list[GateResult], skip: tuple[str, ...] = ()) -> bool:
    return all(g.passed for g in gates if g.id not in skip)


def completeness(gates: list[GateResult]) -> dict:
    return {
        "gates": [g.model_dump() for g in gates],
        "passed": sum(1 for g in gates if g.passed),
        "total": len(gates),
    }
