# Karkhana Voice onboarding

## Bolna

1. Create a Bolna API key and ensure the account has an adequate wallet balance.
2. Deploy the API behind a public HTTPS origin and place that exact origin in `PUBLIC_BASE_URL`.
3. Check that the transcriber, synthesizer, voice ID, telephony provider, and language in each `agents/*/agent.json` are currently accepted by your account. The handoff explicitly warns that model/voice pairs can be rejected at runtime.
4. Run `python -m scripts.create_agent --agent all`, copy its three printed agent IDs to `.env`, and restart the API.
5. Set distinct, high-entropy `WEBHOOK_SECRET` and `TOOL_TOKEN` values in `.env`. Configure the matching `X-Webhook-Secret` callback header for each agent in Bolna; custom headers are not set by the provisioning script because the current account schema is unverified.
6. Verify `/health`, `/api/agents`, and Bolna webhook-delivery history. Test first with team-owned or explicitly opted-in numbers.

## Vercel deployment

The repository includes a FastAPI entrypoint and a once-per-minute authenticated cron endpoint. Vercel does not provide durable local disk or a permanently running scheduler, so create/connect persistent PostgreSQL first and configure `DATABASE_URL` in the Vercel project. Set `CRON_SECRET` there as well; Vercel sends it as the cron request's `Authorization` header. The app refuses to start on Vercel with SQLite.

This workspace is not a Git repository. To deploy the local folder, install the Vercel CLI, authenticate locally with `vercel login`, and run `vercel --prod`. Never paste Vercel or Bolna credentials into chat. After the first deploy, set `PUBLIC_BASE_URL` to its HTTPS URL, provision all agents from the local project, add their returned IDs to Vercel, and redeploy. Configure and test each agent's webhook URL and `X-Webhook-Secret` header in Bolna's Webhook Configuration.

## People and schedules

- Use the Control Room workflow form to record a real recipient's name, phone, role, allowed local call window, and explicit opt-in before manually placing Close/Open calls.
- An `owner` or `purchaser` with consent is eligible for the scheduled Open brief. Set `OPEN_BRIEF_TIME` in `.env`; the service scheduler starts it once daily when the person's call window permits.
- `supervisor` must be separately opted in before breakdown escalation is recorded.
- Record a real supplier's consent and the matching open-PO contact before using Supplier ETA. Never use the seeded supplier names as real contacts.

## Validation

Run `python -m pytest -q`; review the synthetic data label and the expected 2 Red / 1 Amber / 6 Green / 1 Over-stock breakdown before a demo. Keep simulated calls separate from pilot evidence in [pilot-log.md](./pilot-log.md).
