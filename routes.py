import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

import vinsolutions_client as vs
from config import (
    CONNECTOR_API_KEY,
    RECENT_LEAD_DAYS,
    VINSOLUTIONS_DEALER_ID,
    VINSOLUTIONS_LEADS_PATH,
    VINSOLUTIONS_USER_ID,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/vinsolutions", tags=["VinSolutions"])

# Our own id on every lead, so /leadAssociations can hand back the CRM leadId.
REFERENCE_KEY = "zenvykRef"

# Cox VehicleInterestModel / VehicleStatusModel enums.
INTERESTS = {"buy", "lease", "sell", "trade-in", "test-drive"}
STATUSES = {"new", "used", "certified"}


class LeadRequest(BaseModel):
    first_name: str = Field(..., min_length=1)
    last_name: Optional[str] = None
    phone: str = Field(..., min_length=7)
    email: Optional[str] = None
    # Vehicle the caller wants (buy / lease / test-drive) or is selling.
    interest: str = "buy"
    vin: Optional[str] = None
    vehicle_year: Optional[int] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_trim: Optional[str] = None
    new_or_used: Optional[str] = None
    vehicle_of_interest: Optional[str] = None
    # Trade-in, if they have one.
    trade_in: Optional[bool] = None
    trade_year: Optional[int] = None
    trade_make: Optional[str] = None
    trade_model: Optional[str] = None
    trade_mileage: Optional[int] = None
    appointment_request: Optional[str] = None
    source: str = "Voice Agent"
    notes: Optional[str] = None
    dealer_id: Optional[int] = None
    # CRM user the contact search runs as (required by Cox).
    user_id: Optional[int] = None

    # The voice agent fills these from speech ("61,000", "yes", "Trade in"):
    # coerce what we can and drop the rest, so a lead is never rejected over a field.
    @field_validator("vehicle_year", "trade_year", "trade_mileage", "dealer_id", "user_id",
                     mode="before")
    @classmethod
    def _loose_int(cls, value):
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return int(digits) if digits else None

    @field_validator("trade_in", mode="before")
    @classmethod
    def _loose_bool(cls, value):
        text = _norm(value)
        if text in {"true", "yes", "y", "1"}:
            return True
        if text in {"false", "no", "n", "0"}:
            return False
        return None

    @field_validator("interest", mode="before")
    @classmethod
    def _loose_interest(cls, value):
        return _norm(value).replace(" ", "-").replace("tradein", "trade-in") or "buy"


def _digits(phone: str) -> str:
    d = "".join(ch for ch in phone if ch.isdigit())
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def _vehicle(interest, year, make, model, trim=None, vin=None, status=None,
             mileage=None, comment=None) -> dict:
    v = {
        "interest": interest,
        "status": status if status in STATUSES else "unknown",
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "vin": vin,
        "comment": comment,
    }
    if mileage is not None:
        v["odometer"] = {"statusModel": "unknown", "value": mileage}
    return {k: val for k, val in v.items() if val not in (None, "")}


def build_lead_payload(req: LeadRequest, reference: str) -> List[dict]:
    """Map a caller's details onto Cox's ProspectModel (POST /leadSubmissions)."""
    names = [{"part": "first", "type": "individual", "value": req.first_name}]
    if req.last_name:
        names.append({"part": "last", "type": "individual", "value": req.last_name})
    contact = {"names": names, "mobilePhone": _digits(req.phone)}
    if req.email:
        contact["emails"] = [{"preferredContact": True, "value": req.email}]

    vehicles = []
    interest = req.interest if req.interest in INTERESTS else "buy"
    if any([req.vehicle_year, req.vehicle_make, req.vehicle_model, req.vin,
            req.vehicle_of_interest]):
        vehicles.append(_vehicle(interest, req.vehicle_year, req.vehicle_make,
                                 req.vehicle_model, req.vehicle_trim, req.vin,
                                 (req.new_or_used or "").lower(),
                                 comment=req.vehicle_of_interest))
    if req.trade_in or any([req.trade_year, req.trade_make, req.trade_model]):
        vehicles.append(_vehicle("trade-in", req.trade_year, req.trade_make,
                                 req.trade_model, status="used",
                                 mileage=req.trade_mileage))

    comment = " | ".join(
        part for part in [
            req.notes,
            f"Appointment request: {req.appointment_request}" if req.appointment_request else None,
        ] if part
    )
    prospect = {
        "dealerId": req.dealer_id or int(VINSOLUTIONS_DEALER_ID),
        "leadType": "internet",
        # "acquisition" = the dealer buying the caller's vehicle outright.
        "opportunityType": "acquisition" if interest == "sell" else "sales",
        "leadProvider": {"name": "Zenvyk AI", "service": req.source},
        "referenceIds": {REFERENCE_KEY: reference},
        "traits": {"customerInitiated": True},
        "customer": {"contact": contact, **({"comment": comment} if comment else {})},
    }
    if vehicles:
        prospect["vehicles"] = vehicles
    return [prospect]


# Existing leads of these types are not sales conversations.
NON_SALES_LEAD_TYPES = {"SERVICE", "PARTS_ORDER"}


def _norm(value) -> str:
    return str(value or "").strip().casefold()


def _parse_utc(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


async def find_recent_lead(req: LeadRequest, dealer_id: int, user_id: int) -> Optional[dict]:
    """The caller's newest open sales lead from the last RECENT_LEAD_DAYS days.

    Matches on phone AND first name: a household shares one phone, and a
    different person on it is a different customer (VinSolutions agrees)."""
    phone = _digits(req.phone)
    if len(phone) != 10 or not user_id:
        return None
    contacts = [
        c for c in await vs.find_contacts_by_phone(dealer_id, user_id, phone)
        if _norm((c.get("ContactInformation") or {}).get("FirstName")) == _norm(req.first_name)
    ]
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_LEAD_DAYS)
    newest = None
    for contact in contacts:
        for lead in await vs.leads_for_contact(dealer_id, contact["ContactId"]):
            created = _parse_utc(lead.get("createdUtc"))
            if lead.get("leadType") in NON_SALES_LEAD_TYPES or not created or created < cutoff:
                continue
            if newest is None or created > newest[0]:
                newest = (created, {**lead, "contactId": contact["ContactId"]})
    return newest[1] if newest else None


def _same_vehicle(existing: dict, year, make, model) -> bool:
    return (_norm(existing.get("make")) == _norm(make)
            and _norm(existing.get("model")) == _norm(model)
            and (not year or existing.get("year") in (None, 0, year)))


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "")}


async def add_to_existing_lead(lead: dict, req: LeadRequest) -> dict:
    """Add only what the lead doesn't already have: the wanted vehicle and the trade-in."""
    lead_id, href = lead["leadId"], lead["href"]
    notes = " | ".join(p for p in [
        req.vehicle_of_interest, req.notes,
        f"Appointment request: {req.appointment_request}" if req.appointment_request else None,
    ] if p) or None
    added = {"vehicles": 0, "trades": 0}

    if req.vehicle_make or req.vehicle_model or req.vin:
        if not any(_same_vehicle(v, req.vehicle_year, req.vehicle_make, req.vehicle_model)
                   for v in await vs.interest_vehicles(lead_id)):
            status = (req.new_or_used or "").lower()
            await vs.add_interest_vehicles(href, [_clean({
                "year": req.vehicle_year, "make": req.vehicle_make, "model": req.vehicle_model,
                "trim": req.vehicle_trim, "vin": req.vin,
                "inventoryType": {"new": "NEW", "used": "USED",
                                  "certified": "CERTIFIEDPREOWNED"}.get(status, "UNKNOWN"),
                # The API has no lead notes, so the call notes ride on the vehicle.
                "description": notes,
            })])
            added["vehicles"] = 1
            notes = None

    if req.trade_make or req.trade_model:
        if not any(_same_vehicle(t, req.trade_year, req.trade_make, req.trade_model)
                   for t in await vs.trade_vehicles(lead_id)):
            await vs.add_trade_vehicles(href, [_clean({
                "year": req.trade_year, "make": req.trade_make, "model": req.trade_model,
                "mileage": req.trade_mileage, "description": notes,
            })])
            added["trades"] = 1
            notes = None

    return {"added": added, "unsaved_notes": notes}


def _authorized(api_key: Optional[str]) -> bool:
    return bool(CONNECTOR_API_KEY and api_key == CONNECTOR_API_KEY)


@router.post("/submit-lead")
async def submit_lead(req: LeadRequest, x_connector_key: Optional[str] = Header(None)):
    if not _authorized(x_connector_key):
        raise HTTPException(status_code=401, detail="Invalid connector key")

    dealer_id = req.dealer_id or int(VINSOLUTIONS_DEALER_ID)
    user_id = req.user_id or (int(VINSOLUTIONS_USER_ID) if VINSOLUTIONS_USER_ID else 0)
    # Selling their car outright is its own (acquisition) lead, never merged.
    if req.interest != "sell":
        try:
            lead = await find_recent_lead(req, dealer_id, user_id)
            if lead:
                result = await add_to_existing_lead(lead, req)
                return {
                    "success": True,
                    "existing_lead": True,
                    "lead_id": lead["leadId"],
                    "customer_id": lead["contactId"],
                    **result,
                    "message": "The caller already has an open lead with the sales team. "
                               "New details were added to it.",
                }
        except Exception as exc:  # noqa: BLE001
            # Never lose a lead over the duplicate check: fall through and submit.
            log.warning("VinSolutions duplicate check failed, submitting new lead: %s", exc)

    reference = f"zv-{uuid.uuid4().hex[:16]}"
    try:
        await vs.submit_lead(VINSOLUTIONS_LEADS_PATH, build_lead_payload(req, reference))
    except vs.VinSolutionsError as exc:
        return {
            "success": False,
            "error": "vinsolutions_failed",
            "message": "The lead could not be submitted. Route the lead to a human.",
            "status": exc.status,
        }

    # Reply as soon as Cox accepts the lead: the caller is on the line, and the
    # CRM leadId only exists once ingestion finishes (usually within ~10s).
    # Use /lead-status with this reference to fetch it afterwards.
    return {
        "success": True,
        "message": "Lead submitted to VinSolutions.",
        "reference": reference,
    }


@router.get("/lead-status")
async def lead_status(reference: str, x_connector_key: Optional[str] = Header(None)):
    if not _authorized(x_connector_key):
        raise HTTPException(status_code=401, detail="Invalid connector key")
    try:
        association = await vs.lead_association(REFERENCE_KEY, reference)
    except vs.VinSolutionsError as exc:
        return {"found": False, "error": "vinsolutions_failed", "status": exc.status}
    if not association:
        return {"found": False, "message": "Still being processed - try again shortly."}
    return {
        "found": True,
        "lead_id": association.get("leadId"),
        "customer_id": association.get("customerId"),
        "dealer_id": association.get("dealerId"),
    }
