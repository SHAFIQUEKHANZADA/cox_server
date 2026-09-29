# VinSolutions Sales Connector

This service bridges a GHL sales voice agent to Cox Automotive Connect CRM's VinSolutions Lead Management API.

## Current flow

`GHL sales agent -> POST /vinsolutions/submit-lead -> integration.api.coxautoinc.com/vinsolutions/leadsubmissions`

The lead action accepts the caller's identity, phone, email, VIN, vehicle of interest, trade-in, appointment request, notes, and consent. The Cox dashboard currently identifies Lead Submissions as `ApiKey` authentication, so the connector sends the required headers:

- `x-api-key: ...`
- versioned `Accept` and `Content-Type`

## Setup

```powershell
cd vinsolutions
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --reload --port 8000
```

Populate `.env` with the integration credentials and the connector key. Never place credentials in GHL prompts or source code.

The current API material confirms the `/leads` example and required headers, but the exact approved lead schema and OAuth token URL must be confirmed in Cox's Integration environment. `VINSOLUTIONS_LEADS_PATH`, media types, and token settings are configurable for that reason.

## GHL Custom Action

- Method: `POST`
- URL: `https://YOUR-DEPLOYMENT/vinsolutions/submit-lead`
- Header: `X-Connector-Key: YOUR_CONNECTOR_API_KEY`

Example body:

```json
{
  "first_name": "Jane",
  "last_name": "Customer",
  "phone": "6305550147",
  "email": "jane@example.com",
  "vin": "1HG...",
  "vehicle_of_interest": "2025 Honda CR-V Hybrid",
  "new_or_used": "new",
  "trade_in": true,
  "appointment_request": "Saturday afternoon",
  "source": "GHL Voice AI",
  "notes": "Customer wants a test drive",
  "consent": true
}
```

Only tell the caller that the lead was submitted when the response contains `success: true`. On failure, keep the lead details in GHL and transfer or create a human follow-up task.

## Before production

1. Request Integration access for Lead Management.
2. Request Integration access for Digital Showroom, Call Tracking, and Lead Submission if those APIs will be used.
3. Confirm the exact lead request schema, source identifier, dealer ID, and OAuth/token endpoint in the Cox portal.
4. Submit one test lead and verify it appears in VinSolutions.
5. Add the same connector authentication header to every GHL action.