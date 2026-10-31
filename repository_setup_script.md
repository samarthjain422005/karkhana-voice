# Repository operating guide

The original file-content generator was not executable Python and has been replaced by the materialized project files in this folder. This guide records the project collaboration workflow and the v3 decision history so they remain available outside the chat.

Use [README.md](./README.md) for environment setup, running the API, provisioning the three Bolna agents, and running tests. Use [STATUS.md](./STATUS.md) for the latest delivery state. When the user says **"update status"**, regenerate `STATUS.md` from verified project state and report done, in progress, blocked, next three actions, days left, real calls made, and the submission checklist.

## 7A. Working workflow and decision history

### Human + AI working loop

1. The user keeps `STATUS.md` current. Saying **"update status"** means regenerate it with done, in progress, blocked, next three actions, days left, real calls made, and the submission checklist.
2. **"go build"** triggers the first build output, following the source handoff's Section 19 file list.
3. Every assistant turn follows: a 3-line plan; complete files with full paths; then **Run it / Verify it / What can break**.
4. The user runs the project, makes calls only to team-owned or explicitly opted-in numbers, and shares errors, transcripts, and execution IDs. The assistant fixes bugs and plainly acknowledges when its earlier code was wrong.
5. If a Bolna detail is not verified by the supplied documentation, say **"not verified"** and request the relevant docs page or fetch the official docs when browsing is available.
6. Ask at most one clarifying question per turn. If scope must be cut, follow the cut order in Section 16 of the source handoff.
7. Earlier verbal decisions not in the project files must be added here by the user; do not invent missing history.

### v3 decision log (from idea.md)

| # | Change | Why |
|---|---|---|
| 1 | Five call types collapse into three agents (Close, Open, Alert). | Fewer prompts, failure modes, and minutes per factory; testable in four days. |
| 2 | Live in-call validation via Bolna custom functions. | Unlike prompt-injected values and after-call checks, this can validate before read-back. The live schema still must be verified before implementation. |
| 3 | Flat-rate model configuration using preferred-list models. | Keeps voice cost at the flat rate; off-list models bill separately. |
| 4 | Abuse controls on judge mode. | A public "call me now" button could dial strangers or burn the wallet. |
| 5 | Feature triage with a score across 24 candidates. | Four days is the real constraint; most features move to "next 30 days" or "later". |
| 6 | Watchtower adds over-stock, reorder suggestions, and supplier scorecard lanes. | The problem statement included over-ordering to be safe without a feature to address it. |
| 7 | Platform layer adds escalation matrix, call windows, cost-breakdown usage metering, outbound webhooks, and a printable daily sheet. | Makes the product sellable without building ERP adapters. |
| 8 | Bolna details previously marked "not verified" were checked against docs fetched Oct 27. | See Section 9 of the source handoff; re-check current docs before relying on changing API details. |

### Ideas merged into v3

| Idea | Becomes | Tier |
|---|---|---|
| Godown Voice v2 (reconcile by exception, guardrails, shortage engine, briefing) | Close + Open agents, ledger, shortage engine | 0 and 1 |
| Supply Chain Watchtower | Layer 3 backend rules voiced by Open | 1 |
| Factory Hotline | Alert agent, breakdown mode | 1 |
| Shift Handover Memory | Close segment and Open briefing | 2 |
| Self-healing supply chain | Alert supplier mode, opt-in only | 2 |
| Karigar Tally | Count-only production output inside Close; no wages | 1 (output only) |
| Owner note | Spoken external signal in Open; adds supplier delay days | 2 |

### Architecture intent

```text
CAPTURE                         LEDGER                     WATCHTOWER
Close --events/items---------> append-only events -------> signals and risk score
       (reconcile + handover)  incidents, POs, approvals   Red/Amber/Green
Alert --ETA/ack--------------> incidents                  over-stock and reorder
Open  --approvals/notes------> POs and approvals          ranked list
        ^          |
        |          +-- live validate_entry / get_stock custom functions
        +---------------- ACTION
Open: morning brief, incoming handover, owner note
Alert: breakdown dispatch + escalation, supplier ETA
Non-voice: daily sheet, draft PO, outbound webhooks
```

### Current implementation boundary

The repository currently implements three agent definitions, workflow APIs and scheduler, the dashboard, persisted ledger and workflow records, and post-call guardrails. Vercel deployment files now expose the FastAPI app and an authenticated once-per-minute scheduler endpoint; production use still requires a persistent PostgreSQL provider and dashboard configuration. Bolna live custom-function validation, external outbound webhooks, a printable daily sheet, and a real deployment/call have not been verified or completed. Keep those claims distinct from the intended architecture above.

## Run it

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m scripts.seed_demo
python -m uvicorn apps.api.main:app --reload
```

## Verify it

```powershell
python -m pytest -q
```

Expected: all tests pass. Live calls additionally require Bolna credentials, a public HTTPS callback, configured agent IDs and callback secret, a funded wallet, and explicitly opted-in recipients.

## What can break

1. Bolna model/voice choices, live custom-function schemas, and webhook headers must be verified against the current account and official docs.
2. The deadline date is Oct 31, 2026; its cutoff time is not confirmed in the supplied handoff.
3. Synthetic demo data and passing tests are not evidence of a live deployment or real pilot calls.
