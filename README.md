# Karkhana Voice

Karkhana Voice is a phone-first control room for small factories. It provisions three Bolna agents:

- **Close** — shift reconciliation, opening count, confirmed BOM backflush, scrap, and supervisor handover capture.
- **Open** — scheduled/manual top-three risk brief, approval logging (never an automatic purchase), supplier notes, and incoming-shift handover acknowledgements.
- **Alert** — opted-in technician breakdown dispatch with a persisted supervisor escalation timer, plus opt-in ETA confirmation for an existing purchase order.

The API also includes an append-only SQLite ledger, shared quantity/unit guardrails, transparent Watchtower scores, idempotent terminal webhooks, stuck-call polling, bounded Close retries, abuse limits, and a mobile-friendly Control Room.

**Aarav Pumps, its inventory, suppliers, purchase orders, work order, and all sample risk results are synthetic demo data.** No real pilot calls or business outcomes are implied. The handoff describes a live Bolna custom-function schema as unverified, so the MVP uses after-call guardrails rather than inventing the tool config.

## Requirements

- Python 3.11 or newer (the `tzdata` dependency supplies the India time zone on Windows)
- Bolna API key and wallet balance for live calls
- A public HTTPS callback URL for Bolna webhooks
- Bolna-approved provider/model/voice pairs for each agent (verify in the current account)

## Run it

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `BOLNA_API_KEY` and `PUBLIC_BASE_URL` in `.env`, then provision **all three agents**:

```powershell
python -m scripts.create_agent --agent all
```

Copy the printed `BOLNA_AGENT_ID_CLOSE`, `BOLNA_AGENT_ID_OPEN`, and `BOLNA_AGENT_ID_ALERT` values into `.env`; restart after setting them. The script creates agents remotely and does not write credentials or IDs into source files.
Before accepting callbacks, set a unique, high-entropy `WEBHOOK_SECRET` in `.env` and configure the matching `X-Webhook-Secret` header for all three agents in Bolna. Set a separate `TOOL_TOKEN`; the optional live-tool endpoint remains disabled until configured. The provisioning script does not configure custom webhook headers because the Bolna account's current schema is not verified.

## Deploy on Vercel

Vercel's Python runtime can host this FastAPI app, but its filesystem is not persistent and it does not keep a continuous worker alive. This project therefore requires a persistent PostgreSQL database on Vercel (or a connected provider such as Neon), and uses the configured Vercel Cron Job to run the scheduler once per minute. Configure these environment variables in the Vercel project before deploying:

- `DATABASE_URL`: persistent PostgreSQL connection string. The app uses the `psycopg` driver; use a `postgresql://` or `postgres://` URL.
- `PUBLIC_BASE_URL`: the production `https://<project>.vercel.app` URL, after the first deployment.
- `BOLNA_API_KEY`: a newly rotated key; never use the key previously pasted into chat.
- `WEBHOOK_SECRET`, `TOOL_TOKEN`, and `CRON_SECRET`: three different high-entropy secrets. Set `CRON_SECRET` in Vercel so Vercel automatically sends it as the cron request's `Authorization: Bearer ...` header.
- `BOLNA_AGENT_ID_CLOSE`, `BOLNA_AGENT_ID_OPEN`, and `BOLNA_AGENT_ID_ALERT`: add after provisioning agents against the production `PUBLIC_BASE_URL`.

The app validates PostgreSQL configuration at startup on Vercel. Do not deploy with the local SQLite URL. Agent webhook custom headers must be configured in Bolna's agent Webhook Configuration; this project does not automate that dashboard setting. The callback header must be `X-Webhook-Secret` with the exact `WEBHOOK_SECRET` value.

After connecting your Git repository to Vercel and adding the variables, deploy through the Vercel dashboard or its CLI. Confirm `/health`, `/api/agents`, database persistence after a fresh invocation, the scheduled `/api/cron` run, and webhook delivery before making any calls. Cron is minute-granularity, so incident escalation can be delayed by up to roughly one minute beyond its configured due time.

This workspace is not currently a Git repository. To deploy the local folder without Git, install and authenticate the Vercel CLI, then deploy:

```powershell
npm install --global vercel
vercel login
vercel --prod
```

Create/connect the persistent PostgreSQL database and set its `DATABASE_URL` in the Vercel project before the production deployment. After the first deployment, set `PUBLIC_BASE_URL` to the assigned HTTPS URL in both Vercel and local `.env`, then redeploy. Provision the three agents from the local project with `python -m scripts.create_agent --agent all`; add their IDs to the Vercel project's environment variables and redeploy again. Configure the `X-Webhook-Secret` custom header through each agent's Bolna Webhook Configuration and send a test callback before any live call.

Start the service:

```powershell
python -m scripts.seed_demo
python -m uvicorn apps.api.main:app --reload
```

Open http://127.0.0.1:8000. Without Bolna setup, the synthetic Watchtower, dashboard, handover/incident views, and what-if supplier signal still run. The API status at `/api/agents` shows which IDs are configured.

## Run the workflows

1. **Close / Open:** use the Control Room form to select Close shift/opening count or Open morning brief/incoming handover. The recipient must explicitly opt in; the call window is checked before Bolna is called.
2. **Breakdown Alert:** report the machine and provide separately opted-in technician and supervisor contacts. Alert calls the technician. If the call fails or completes without the required acknowledgement line, the persisted scheduler escalates to the supervisor. The incident can also be acknowledged by a human in the dashboard.
3. **Supplier ETA Alert:** select an existing open PO and provide a supplier phone only after their explicit opt-in. The agent can update only that PO's ETA; no new order or price discussion is supported.
4. **Scheduled Open brief:** an opted-in `owner` or `purchaser` registered through the workflow form can receive one daily brief after `OPEN_BRIEF_TIME`, within their stored call window. The poller is restart-safe and only considers opted-in records.

The consent boxes record the caller's attestation; they do not prove consent. Use only a team-owned phone or a person who has actually agreed to the specific call. Do not configure synthetic sample suppliers as real contacts.

## Verify it

```powershell
python -m pytest -q
```

The seeded dashboard should show **2 Red, 1 Amber, 6 Green, and 1 Over-stock**. `eval/` tests score bands and components, completed-only/idempotent webhook behavior, BOM backflush, the Open owner-note what-if, alert consent and escalation behavior, and agent setup metadata. Scripted and synthetic data are not pilot evidence.

## What can break

1. Bolna may reject the configured ASR/TTS model and voice pair; verify live provider/model/voice choices in the account before provisioning.
2. Webhooks require public HTTPS. Configure the exact host in `PUBLIC_BASE_URL` and inspect Bolna webhook delivery after agent creation.
3. Live calls require the three configured agent IDs, a funded wallet, an allowed local-time call window, and real recipient consent.

## Scope and known limits

External feeds, ERP integrations, login/billing, real supplier setup, and vendor-specific webhook signature formats are not claimed. The app is designed as a buildathon demo and is not production-ready for public telephony without authentication, legal/compliance review, and hardened contact administration.
