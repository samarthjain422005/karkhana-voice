# Consent and call handling

This is implementation guidance, not legal advice. Review local telecom and privacy requirements before commercial use.

## Before any call

- Call only a team-owned number or a recipient who explicitly agreed to this type of call.
- Record the recipient, phone, consent timestamp, and consent method. The browser checkboxes are an operator attestation, not proof of consent.
- Record supplier consent separately before supplier ETA calls. The seeded sample suppliers are synthetic and have no real consent or phone.
- Respect the stored call window and the agent's AI/recording disclosure.
- Configure a high-entropy `WEBHOOK_SECRET` and matching `X-Webhook-Secret` header in Bolna before enabling callbacks. Callbacks fail closed until the secret is configured.
- Do not request OTPs, card details, Aadhaar, bank details, or wage information.

## Data handling

- Raw call payloads, transcripts, and execution IDs are retained in the local database for demo/pilot review. Avoid collecting personal or sensitive information in a call.
- The public demo endpoints return only limited call metadata and transcripts with phone-like number strings redacted; they do not expose webhook payloads or stored phone numbers.
- For a real deployment, configure authentication and role-based access, retention/deletion controls, secure backups, transport security, and a grievance contact before using personal data.

## Human escalation

Breakdown calls escalate to the separately opted-in supervisor on no-answer, busy, failure, or completed call without a clear acknowledgement. A human can acknowledge an incident from the Control Room.
