# Karkhana Voice status

**Last verified:** 2026-10-31

**Submission deadline:** 2026-10-31; exact cutoff time and time zone are not confirmed in the supplied handoff. The official submission page was checked, but it does not display the cutoff time. **Days left: 0** (deadline date; submission window may already be closed).

## Done

- Implemented the Close, Open, and Alert agent definitions and provisioning script.
- Implemented workflow APIs, consent and call-window gating, scheduler, retries, breakdown escalation, and dashboard controls.
- Added ledger and workflow persistence, idempotent terminal webhook processing, output quantity review, and webhook-secret enforcement.
- Added setup, onboarding, consent, and submission documentation.
- Added Vercel FastAPI entrypoint, persistent-Postgres enforcement, authenticated scheduler endpoint, and a one-minute Vercel Cron definition.
- Created local `.env` with fresh random webhook/tool/cron secrets; no Bolna API key or agent IDs were inserted.
- Verified the test suite: **18 passed**; Python compilation passed.

## In progress

- No live Bolna provisioning, Vercel deployment, webhook delivery, or live-call validation has been verified.
- Submission assets and public submission links are not confirmed in this workspace.

## Blocked

- Vercel deployment requires a Vercel account/CLI login, a persistent PostgreSQL database URL, and the production domain. The local `.env` still has no Bolna API key or agent IDs.
- Live calls require the user's newly rotated Bolna API key, funded wallet, public HTTPS callback URL, provisioned agent IDs, matching webhook secret configuration, and actual opt-in from each recipient.
- Submission completion cannot be confirmed without the registration email, public repository/live URL, and accessible pitch deck or video links.
- The official page does not state the deadline cutoff time; verify directly with the organizer if the form is still accepting submissions.

## Next 3 actions

1. Check whether the official submission form is still open; submit using the registration email and add the public project and pitch links if ready.
2. If the submission window remains open and live setup is desired, configure secrets and Bolna credentials, provision the three agents, and verify webhook delivery.
3. Place a test call only to a team-owned or explicitly opted-in number; record the execution ID, outcome, and learning in `docs/pilot-log.md`.

## Real calls made

**None recorded.** Passing automated tests and synthetic/demo data are not real-call evidence.

## Submission checklist

- [ ] Public repository link confirmed; this workspace reports no Git repository.
- [ ] Live URL works from a phone without login, or an honest demo alternative is supplied.
- [x] Project README includes run steps; `.env` is gitignored.
- [ ] Demo video (2 minutes or less) uploaded with "Anyone with the link" access.
- [ ] Pitch deck uploaded with "Anyone with the link" access.
- [x] Project description is under 200 characters (see `docs/SUBMISSION.md`).
- [ ] Submission form completed using the registration email.
- [ ] Team size, team name, and project name entered.
- [ ] Submission confirmation received.
