"""Request bodies for the FastAPI wrapper (pydantic)."""
from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class CheckinBody(BaseModel):
    language: str = "en"
    fields: dict | None = None
    text: str | None = None


class LabResultBody(BaseModel):
    creatinine_mg_dl: float | None = None
    potassium_mmol_l: float | None = None


class OrderBody(BaseModel):
    reason: str = "red alert"


class RevokeBody(BaseModel):
    requester: str | None = None


class DeviceMessage(BaseModel):
    device_id: str
    patient_id: str
    ts: str
    nonce: str
    readings: dict
    signature: str | None = None
