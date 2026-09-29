import os

from dotenv import load_dotenv

load_dotenv()

VINSOLUTIONS_BASE_URL = os.getenv(
    "VINSOLUTIONS_BASE_URL", "https://integration.api.vinsolutions.com"
).rstrip("/")
VINSOLUTIONS_LEADS_PATH = os.getenv("VINSOLUTIONS_LEADS_PATH", "/leadSubmissions")
VINSOLUTIONS_TOKEN_URL = os.getenv(
    "VINSOLUTIONS_TOKEN_URL", "https://authentication.vinsolutions.com/connect/token"
).strip()
VINSOLUTIONS_ACCESS_TOKEN = os.getenv("VINSOLUTIONS_ACCESS_TOKEN", "").strip()
# Each Cox API has its own key; Lead Submissions is the one this service posts to.
VINSOLUTIONS_API_KEY = (
    os.getenv("VINSOLUTIONS_API_KEY", "").strip()
    or os.getenv("VIN_KEY_LEADSUBMISSIONS", "").strip()
)
VINSOLUTIONS_CLIENT_ID = os.getenv("VINSOLUTIONS_CLIENT_ID", "").strip()
VINSOLUTIONS_CLIENT_SECRET = os.getenv("VINSOLUTIONS_CLIENT_SECRET", "").strip()
VINSOLUTIONS_DEALER_ID = os.getenv("VINSOLUTIONS_DEALER_ID", "").strip()
VINSOLUTIONS_USER_ID = os.getenv("VINSOLUTIONS_USER_ID", "").strip()
# POST /leadSubmissions is a v2 endpoint; /leadAssociations is v1.
VINSOLUTIONS_ACCEPT = os.getenv(
    "VINSOLUTIONS_ACCEPT", "application/vnd.coxauto.v2+json"
).strip()
VINSOLUTIONS_CONTENT_TYPE = os.getenv(
    "VINSOLUTIONS_CONTENT_TYPE", "application/vnd.coxauto.v2+json"
).strip()
CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY", "").strip()
# Lead Management (contact search, existing leads, vehicles) has its own key.
VIN_KEY_LEADMANAGEMENT = os.getenv("VIN_KEY_LEADMANAGEMENT", "").strip()
# Digital Showroom (lead notes, lead status) has its own key too.
VIN_KEY_DIGITALSHOWROOM = os.getenv("VIN_KEY_DIGITALSHOWROOM", "").strip()
# A caller with an open lead newer than this gets their details added to it
# instead of a second lead.
RECENT_LEAD_DAYS = int(os.getenv("RECENT_LEAD_DAYS", "30"))