import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ.setdefault("VINSOLUTIONS_DEALER_ID", "6082")

from routes import LeadRequest, build_lead_payload


def test_build_lead_payload_matches_cox_prospect_model():
    [prospect] = build_lead_payload(
        LeadRequest(
            first_name="Jane",
            last_name="Customer",
            phone="+1 (630) 555-0147",
            email="jane@example.com",
            interest="buy",
            vehicle_year=2025,
            vehicle_make="Honda",
            vehicle_model="CR-V",
            new_or_used="new",
            trade_in=True,
            trade_year=2019,
            trade_make="Honda",
            trade_model="Civic",
            trade_mileage=64000,
            appointment_request="Saturday afternoon",
            dealer_id=6082,
        ),
        reference="zv-test",
    )

    assert prospect["dealerId"] == 6082
    assert prospect["leadType"] == "internet"
    assert prospect["opportunityType"] == "sales"
    assert prospect["referenceIds"] == {"zenvykRef": "zv-test"}
    contact = prospect["customer"]["contact"]
    assert contact["names"][0] == {"part": "first", "type": "individual", "value": "Jane"}
    assert contact["mobilePhone"] == "6305550147"
    assert contact["emails"][0]["value"] == "jane@example.com"
    wanted, trade = prospect["vehicles"]
    assert (wanted["interest"], wanted["status"], wanted["model"]) == ("buy", "new", "CR-V")
    assert trade["interest"] == "trade-in"
    assert trade["odometer"]["value"] == 64000
    assert "Saturday afternoon" in prospect["customer"]["comment"]


def test_unknown_interest_falls_back_to_buy_and_no_vehicle_is_omitted():
    [prospect] = build_lead_payload(
        LeadRequest(first_name="Sam", phone="2135550100", interest="window-shopping", dealer_id=6082),
        reference="zv-x",
    )
    assert "vehicles" not in prospect
    assert "emails" not in prospect["customer"]["contact"]


def test_selling_outright_is_an_acquisition_lead():
    [prospect] = build_lead_payload(
        LeadRequest(first_name="Chad", phone="7047494408", interest="sell",
                    vehicle_year=2019, vehicle_make="Harley-Davidson", vehicle_model="Road Glide",
                    new_or_used="used", dealer_id=6082),
        reference="zv-sell",
    )
    assert prospect["opportunityType"] == "acquisition"
    assert prospect["vehicles"][0]["interest"] == "sell"


# --- duplicate check -----------------------------------------------------------
import asyncio
from datetime import datetime, timedelta, timezone

import routes
import vinsolutions_client as vs


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _fake_crm(monkeypatch, contacts, leads, interests=(), trades=()):
    posted = {"interest": [], "trade": []}

    async def find(dealer, user, phone):
        return contacts

    async def leads_for(dealer, cid):
        return leads.get(cid, [])

    async def interest(lead_id):
        return list(interests)

    async def trade(lead_id):
        return list(trades)

    async def add_i(href, vehicles):
        posted["interest"].append(vehicles)

    async def add_t(href, vehicles):
        posted["trade"].append(vehicles)

    monkeypatch.setattr(vs, "find_contacts_by_phone", find)
    monkeypatch.setattr(vs, "leads_for_contact", leads_for)
    monkeypatch.setattr(vs, "interest_vehicles", interest)
    monkeypatch.setattr(vs, "trade_vehicles", trade)
    monkeypatch.setattr(vs, "add_interest_vehicles", add_i)
    monkeypatch.setattr(vs, "add_trade_vehicles", add_t)
    return posted


def _contact(cid, first):
    return {"ContactId": cid, "ContactInformation": {"FirstName": first}}


def _lead(lid, days_ago, lead_type="INTERNET"):
    return {"leadId": lid, "href": f"https://api.vinsolutions.com/leads/id/{lid}",
            "leadType": lead_type, "createdUtc": _iso(days_ago)}


def test_recent_lead_found_for_same_name_and_phone(monkeypatch):
    _fake_crm(monkeypatch, [_contact(1, "Test")], {1: [_lead(10, 3)]})
    req = LeadRequest(first_name="test", phone="+1 (213) 555-0142")
    lead = asyncio.run(routes.find_recent_lead(req, 6082, 29668))
    assert lead["leadId"] == 10 and lead["contactId"] == 1


def test_household_member_and_old_or_service_leads_are_ignored(monkeypatch):
    _fake_crm(monkeypatch, [_contact(1, "Lisa"), _contact(2, "Test")],
              {1: [_lead(11, 1)], 2: [_lead(12, 45), _lead(13, 2, "SERVICE")]})
    req = LeadRequest(first_name="Test", phone="2135550142")
    assert asyncio.run(routes.find_recent_lead(req, 6082, 29668)) is None


def test_only_new_vehicles_are_added_to_existing_lead(monkeypatch):
    posted = _fake_crm(monkeypatch, [], {},
                       interests=[{"year": 2025, "make": "Honda", "model": "CR-V"}],
                       trades=[])
    req = LeadRequest(first_name="Test", phone="2135550142", vehicle_make="Honda",
                      vehicle_model="CR-V", trade_make="Toyota", trade_model="Camry",
                      trade_mileage=50000, notes="Wants Saturday")
    result = asyncio.run(routes.add_to_existing_lead(_lead(10, 1), req))
    assert posted["interest"] == []  # CR-V already on the lead
    assert posted["trade"][0][0]["model"] == "Camry"
    assert posted["trade"][0][0]["description"] == "Wants Saturday"
    assert result == {"added": {"vehicles": 0, "trades": 1}, "unsaved_notes": None}


def test_spoken_values_never_reject_the_lead():
    req = LeadRequest(first_name="Sam", phone="2135550100", vehicle_year="twenty twenty-six",
                      trade_year="2018", trade_mileage="61,000 miles", trade_in="Yes",
                      interest="Trade in", dealer_id="")
    assert (req.vehicle_year, req.trade_year, req.trade_mileage) == (None, 2018, 61000)
    assert req.trade_in is True and req.interest == "trade-in" and req.dealer_id is None
