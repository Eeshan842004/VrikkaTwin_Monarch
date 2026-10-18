"""FastAPI wrapper over the services layer (§19; Part 6). Thin by design: every endpoint calls one Services method,
so role, consent and audit are enforced in exactly one place. The Streamlit app calls the same services in-process.

    python -m uvicorn vrikka.api.main:app --port 8000        # docs at http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from vrikka import __version__
from vrikka.api.deps import services, session
from vrikka.api.schemas import CheckinBody, DeviceMessage, LabResultBody, LoginRequest, OrderBody, RevokeBody
from vrikka.security.auth import Session
from vrikka.security.rbac import AccessDenied

SessionDep = Annotated[Session, Depends(session)]

app = FastAPI(title="VrikkaTwin API", version=__version__,
              description="Kidney digital twin (research prototype; synthetic data only; not a medical device).")


def _guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except AccessDenied as e:
        raise HTTPException(status_code=403, detail=e.reason) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/login")
def login(body: LoginRequest) -> dict:
    s = services().login(body.username, body.password)
    if s is None:
        raise HTTPException(status_code=401, detail="wrong username or password")
    return {"token": s.token, "role": s.role, "subject": s.subject}


@app.get("/triage")
def triage(s: SessionDep) -> list[dict]:
    return _guard(services().list_triage, s)


@app.get("/patients/{pid}")
def patient(pid: str, s: SessionDep) -> dict:
    return _guard(services().read_patient, s, pid)


@app.post("/patients/{pid}/checkin")
def checkin(pid: str, body: CheckinBody, s: SessionDep) -> dict:
    return _guard(services().submit_checkin, s, pid, body.language, body.fields, body.text)


@app.post("/patients/{pid}/kidney-test")
def order_test(pid: str, body: OrderBody, s: SessionDep) -> dict:
    return {"task_id": _guard(services().order_kidney_test, s, pid, body.reason)}


@app.get("/tasks")
def tasks(s: SessionDep, status: str | None = None) -> list[dict]:
    return _guard(services().list_tasks, s, status)


@app.post("/tasks/{task_id}/result")
def lab_result(task_id: int, body: LabResultBody, s: SessionDep) -> dict:
    return _guard(services().record_lab_result, s, task_id, body.creatinine_mg_dl, body.potassium_mmol_l)


@app.post("/patients/{pid}/consent/revoke")
def revoke(pid: str, body: RevokeBody, s: SessionDep) -> dict:
    return {"revoked": _guard(services().revoke_consent, s, pid, body.requester)}


@app.get("/patients/{pid}/fhir")
def fhir(pid: str, s: SessionDep) -> dict:
    return _guard(services().export_fhir, s, pid)


@app.post("/devices/readings")
def device_reading(msg: DeviceMessage) -> dict:
    return services().ingest_device(msg.model_dump())


@app.get("/audit/verify")
def audit_verify(s: SessionDep) -> dict:
    return _guard(services().audit_status, s)
