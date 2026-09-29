import os

from fastapi import FastAPI

from config import (
    CONNECTOR_API_KEY,
    VINSOLUTIONS_ACCESS_TOKEN,
    VINSOLUTIONS_API_KEY,
    VINSOLUTIONS_CLIENT_ID,
    VINSOLUTIONS_CLIENT_SECRET,
    VINSOLUTIONS_DEALER_ID,
    VINSOLUTIONS_TOKEN_URL,
    VIN_KEY_LEADMANAGEMENT,
)
from routes import router

app = FastAPI(
    title="Zenvyk x VinSolutions Connector",
    description="Bridges a GHL sales agent to Cox Connect CRM Lead Management.",
    version="0.1.0",
)
app.include_router(router)


@app.get("/")
def root():
    return {"service": "Zenvyk x VinSolutions Connector", "docs": "/docs"}


@app.get("/health")
def health():
    has_auth = bool(VINSOLUTIONS_API_KEY) or bool(VINSOLUTIONS_ACCESS_TOKEN) or all(
        [VINSOLUTIONS_TOKEN_URL, VINSOLUTIONS_CLIENT_ID, VINSOLUTIONS_CLIENT_SECRET]
    )
    missing = [
        name
        for name, value in {
            "VINSOLUTIONS_API_KEY": VINSOLUTIONS_API_KEY,
            "VINSOLUTIONS_DEALER_ID": VINSOLUTIONS_DEALER_ID,
            "CONNECTOR_API_KEY": CONNECTOR_API_KEY,
            "VIN_KEY_LEADMANAGEMENT": VIN_KEY_LEADMANAGEMENT,
        }.items()
        if not value
    ]
    if not has_auth:
        missing.append("VINSOLUTIONS_API_KEY")
    return {
        "status": "ok" if not missing else "misconfigured",
        "environment": os.getenv("VINSOLUTIONS_BASE_URL", "integration"),
        "missing_env": missing,
    }