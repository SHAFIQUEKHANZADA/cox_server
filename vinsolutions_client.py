import json
import time
from typing import Any, Dict, List, Optional

import httpx

from config import (
    VINSOLUTIONS_ACCEPT,
    VINSOLUTIONS_ACCESS_TOKEN,
    VINSOLUTIONS_API_KEY,
    VINSOLUTIONS_BASE_URL,
    VINSOLUTIONS_CLIENT_ID,
    VINSOLUTIONS_CLIENT_SECRET,
    VINSOLUTIONS_CONTENT_TYPE,
    VINSOLUTIONS_TOKEN_URL,
    VIN_KEY_LEADMANAGEMENT,
)

V1 = "application/vnd.coxauto.v1+json"
V3 = "application/vnd.coxauto.v3+json"


class VinSolutionsError(Exception):
    def __init__(self, status: int, body: str, step: str):
        self.status = status
        self.body = body
        self.step = step
        super().__init__(f"VinSolutions {step} failed [{status}]: {body[:300]}")


_token_cache: Dict[str, Any] = {"value": "", "expires_at": 0.0}


async def _access_token() -> str:
    if VINSOLUTIONS_ACCESS_TOKEN:
        return VINSOLUTIONS_ACCESS_TOKEN
    if not VINSOLUTIONS_TOKEN_URL or not VINSOLUTIONS_CLIENT_ID or not VINSOLUTIONS_CLIENT_SECRET:
        raise VinSolutionsError(500, "Bearer token or OAuth configuration is missing", "auth")

    if _token_cache["value"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["value"]

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.post(
            VINSOLUTIONS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": VINSOLUTIONS_CLIENT_ID,
                "client_secret": VINSOLUTIONS_CLIENT_SECRET,
                # Cox requires this scope for every third-party application.
                "scope": "PublicAPI",
            },
        )
    if response.status_code >= 400:
        raise VinSolutionsError(response.status_code, response.text, "auth")

    data = response.json()
    token = data.get("access_token")
    if not token:
        raise VinSolutionsError(502, "Token response did not contain access_token", "auth")
    _token_cache.update(
        value=token,
        expires_at=time.time() + int(data.get("expires_in", 3600)),
    )
    return token


async def submit_lead(path: str, payload: List[Dict[str, Any]]) -> list:
    """POST up to 10 prospects to /leadSubmissions (the body is a JSON array)."""
    headers = {
        # Cox is inconsistent about which one it wants: the API Storefront panel
        # shows `x-api-key`, the Lead Management docs show `api_key`. Probed live
        # on 18 Sep 2026 against sandbox Lead Management with a VALID key:
        #     x-api-key only -> 403 {"message":"Invalid or inactive api_key"}
        #     api_key   only -> 401 {"message":"Authorization has been denied"}
        # The 401 is progress — it means the key was accepted and only the bearer
        # is missing. So `api_key` is the one that counts; we send both, which
        # behaves identically to `api_key` alone and covers either gateway.
        "api_key": VINSOLUTIONS_API_KEY,
        "x-api-key": VINSOLUTIONS_API_KEY,
        "Accept": VINSOLUTIONS_ACCEPT,
        "Content-Type": VINSOLUTIONS_CONTENT_TYPE,
    }
    # Cox's product guide: every request needs the bearer token AND the api_key.
    headers["Authorization"] = f"Bearer {await _access_token()}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.post(
            f"{VINSOLUTIONS_BASE_URL}/{path.lstrip('/')}",
            headers=headers,
            # content=, not json=, so httpx keeps the versioned Content-Type.
            content=json.dumps(payload),
        )
    if response.status_code >= 400:
        raise VinSolutionsError(response.status_code, response.text, "submit_lead")
    return response.json() if response.text else []


async def lead_association(reference_key: str, reference_value: str) -> Optional[dict]:
    """Look up the CRM leadId/customerId for a lead we posted, by our referenceId.

    Returns None while the lead is still being ingested (404)."""
    headers = {
        "api_key": VINSOLUTIONS_API_KEY,
        "x-api-key": VINSOLUTIONS_API_KEY,
        "Accept": "application/vnd.coxauto.v1+json",
        "Authorization": f"Bearer {await _access_token()}",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.get(
            f"{VINSOLUTIONS_BASE_URL}/leadAssociations",
            headers=headers,
            params={"ReferenceIdKey": reference_key, "ReferenceIdValue": reference_value},
        )
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise VinSolutionsError(response.status_code, response.text, "lead_association")
    return response.json()

# --- Lead Management API (its own api_key) -----------------------------------

async def _lm_request(method: str, path: str, accept: str, step: str,
                      params: Optional[dict] = None, body: Any = None) -> httpx.Response:
    headers = {
        "api_key": VIN_KEY_LEADMANAGEMENT,
        "x-api-key": VIN_KEY_LEADMANAGEMENT,
        "Accept": accept,
        "Authorization": f"Bearer {await _access_token()}",
    }
    if body is not None:
        headers["Content-Type"] = accept
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.request(
            method,
            f"{VINSOLUTIONS_BASE_URL}/{path.lstrip('/')}",
            headers=headers,
            params=params,
            content=json.dumps(body) if body is not None else None,
        )
    if response.status_code >= 400 and response.status_code != 404:
        raise VinSolutionsError(response.status_code, response.text, step)
    return response


async def find_contacts_by_phone(dealer_id: int, user_id: int, phone: str) -> list:
    """Contacts whose phone exactly matches `phone` (10 digits, as the CRM stores it)."""
    response = await _lm_request(
        "GET", "/gateway/v1/contact", "application/json", "find_contacts",
        params={"dealerId": dealer_id, "userId": user_id, "phone": phone, "pageSize": 50},
    )
    return response.json() if response.status_code == 200 else []


async def leads_for_contact(dealer_id: int, contact_id: int) -> list:
    """The contact's ACTIVE leads, newest first."""
    response = await _lm_request(
        "GET", "/leads", V3, "leads_for_contact",
        params={"dealerId": dealer_id, "contactId": contact_id,
                "leadStatusType": "ACTIVE", "sortBy": "Date", "limit": 100},
    )
    return response.json().get("items", []) if response.status_code == 200 else []


async def interest_vehicles(lead_id: int) -> list:
    response = await _lm_request("GET", "/vehicles/interest", V1, "interest_vehicles",
                                 params={"leadId": lead_id})
    return response.json().get("items", []) if response.status_code == 200 else []


async def trade_vehicles(lead_id: int) -> list:
    response = await _lm_request("GET", "/vehicles/trade", V1, "trade_vehicles",
                                 params={"leadId": lead_id})
    return response.json().get("items", []) if response.status_code == 200 else []


async def add_interest_vehicles(lead_href: str, vehicles: List[dict]) -> None:
    await _lm_request("POST", "/vehicles/interest", V1, "add_interest_vehicles",
                      body={"lead": lead_href, "vehicles": vehicles})


async def add_trade_vehicles(lead_href: str, vehicles: List[dict]) -> None:
    await _lm_request("POST", "/vehicles/trade", V1, "add_trade_vehicles",
                      body={"lead": lead_href, "vehicles": vehicles})
