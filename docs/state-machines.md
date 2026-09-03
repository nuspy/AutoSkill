# State machines

## Skill version

```
draft ─(validation ok)→ testing ─(all steps confirmed, trial accepted)→ tested
tested ─[author: submit]→ submitted_for_review
submitted_for_review ─[reviewer: approved]→ approved
submitted_for_review ─[reviewer: changes_requested]→ changes_requested ─(resubmit)→ submitted_for_review
submitted_for_review ─[reviewer: rejected]→ rejected
submitted_for_review ─[author: withdraw]→ tested
approved ─[project editor: Authorization(publish)]→ published
published ─(newer version published)→ superseded      published ─[Authorization(deprecate)]→ deprecated
draft | testing | tested | changes_requested → discarded
```
Implemented in `backend/autoskill/services/versioning/state_machine.py`. System actors never move a
version beyond `tested`; self-review is blocked unless the admin allows it; publishing needs a review
decision and a human authorization with checklist.

## Trial session

`requested → installed → testing ⇄ suspended → reviewing → decided | removed | abandoned`

## Checkpoint phases (per step and iteration)

`explain → preview → [execute] → verify`, decisions per phase in
`services/tester/checkpoints.py`. Simulated (irreversible) steps can never reach `execute`; real
execution of an irreversible step needs the person's `authorize_execute` on the preview, which mints
the confirmation token the generated tools require.

## Interview procedure

`intake → compute_gates → supervise → ask ⇄ ingest → confirm_summary → finalize`, run by the
deterministic procedure engine (`services/procedures/engine.py`); the supervisor is an LLM decision
at a fixed point, and the deterministic gates always have the last word.

## Improvement proposal

`analyzing → proposed → under_review → accepted | rejected` (`failed` when there is nothing to
improve or the model output was unusable). Accepting never publishes.
