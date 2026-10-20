"""The one services layer (§19, §21; Part 6). Every call from the Streamlit pages or the FastAPI wrapper goes through
here, and every call follows the same steps:

1. the session's role must allow the action (security/rbac.py);
2. patients and family may only touch their own (linked) record;
3. any other role needs a GRANTED, signed, unexpired consent artefact for that patient, requester and data type
   (interop/abdm_consent.py) - checked on every read, so a revoke takes effect at once (test S11);
4. the call is written to the hash-chained audit log (allowed or denied, with the reason);
5. the record leaves with only the fields the role may see, and names are decrypted only for those roles.

Device readings pass the data-integrity gate first (test S10). Red flags run before any risk (whatif/red_flags.py).

Alerts: a red risk level, a red flag, a triple-whammy medicine combination or an ambulance call is sent at once to the
patient, and to the doctor and family only while their consent is GRANTED. Medicines: the daily list starts from the
EHR and can be edited by the patient, family, doctor or ASHA; brand names are resolved to generics (Combiflam ->
ibuprofen + paracetamol) and the sick-day guidance follows the edited list.
"""
from __future__ import annotations

import copy

from vrikka.config import load_yaml
from vrikka.interop import fhir_export
from vrikka.physiology.equations import egfr_ckd_epi_2021, kdigo_stage
from vrikka.security import auth, rbac
from vrikka.security.audit import AuditLog
from vrikka.security.consent import ConsentRegistry
from vrikka.security.crypto import decrypt_text
from vrikka.security.device_gateway import IntegrityGate
from vrikka.services import directory
from vrikka.store import db, repo
from vrikka.whatif import guardrails as gr
from vrikka.whatif import red_flags
from vrikka.whatif.sickday import guidance

CONSENTED_REQUESTERS = ("doctor", "asha", "lab", "family")
RAS = {"arb", "acei"}
DIURETIC = {"thiazide", "loop"}
NSAID = {"nsaid_cyp2c9", "nsaid_other"}
NAME_ROLES = {"doctor", "patient", "family", "asha"}


class Services:
    def __init__(self, db_path=None, audit_path=None, seed_consents: bool = True):
        self.audit = AuditLog(path=audit_path)
        self.consents = ConsentRegistry()
        self.gate = IntegrityGate(self.audit)
        self.con = db.connect(db_path if db_path is not None else ":memory:")
        self.patients = copy.deepcopy(directory.all_patients())   # own copy: edits never leak between sessions
        if seed_consents:
            for pid in self.patients:
                for req in CONSENTED_REQUESTERS:
                    self.consents.grant(pid, req)
        self._meds_seeded: set[str] = set()
        self.audit.append("services_started", patients=len(self.patients))
        self.send_risk_alerts()
        self.audit.checkpoint()

    # ------------------------------------------------------------------ sessions
    def login(self, username: str, password: str) -> auth.Session | None:
        s = auth.login(username, password)
        self.audit.append("login" if s else "login_failed", actor=username, role=s.role if s else None)
        return s

    # ------------------------------------------------------------------ access control
    def _authorize(self, s: auth.Session, action: str, pid: str | None = None) -> None:
        try:
            rbac.require(s.role, action)
            if pid is not None:
                if pid not in self.patients:
                    raise rbac.AccessDenied("unknown_patient")
                if s.role in ("patient", "family") and s.subject != pid:
                    raise rbac.AccessDenied("not_your_record")
                if s.role not in rbac.SELF_ROLES:
                    ok, why = self.consents.check(pid, s.role, rbac.HI_TYPE.get(s.role, "Observation"))
                    if not ok:
                        raise rbac.AccessDenied(f"consent_{why}")
        except rbac.AccessDenied as e:
            self.audit.append("access_denied", actor=s.username, subject=pid, attempted=action, role=s.role,
                              reason=e.reason)
            raise
        self.audit.append(action, actor=s.username, subject=pid, role=s.role)

    def _view(self, s: auth.Session, rec: dict) -> dict:
        out = {k: v for k, v in rec.items() if k != "name_enc"}
        if s.role in NAME_ROLES:
            out["name"] = decrypt_text(rec["name_enc"])
        out["tasks"] = repo.tasks(self.con, rec["patient_id"])
        out["medicines"] = self._medicines(rec["patient_id"])
        out["checkins"] = repo.checkins(self.con, rec["patient_id"])
        lab = next((t for t in out["tasks"] if t["status"] == "resulted"), None)
        if lab and lab["result_flag"] and lab["result_flag"].startswith("kdigo_stage"):
            out["level"], out["advice_keys"] = "purple", ["level.purple", "action.purple"]
        last = out["checkins"][0] if out["checkins"] else None
        out["red_flags"] = last["red_flag"] if last else "none"
        out["sickday"] = guidance(out.get("generics", []), {"fever_excess_c": 1.0 if "fever" in rec.get(
            "events_active", []) else 0, "vomit_episodes": 1 if "gi" in rec.get("events_active", []) else 0},
            out.get("heart_failure", False), out.get("egfr_baseline"), out.get("last_potassium"))
        return rbac.filter_fields(s.role, out)

    # ------------------------------------------------------------------ reads
    def read_patient(self, s: auth.Session, pid: str) -> dict:
        self._authorize(s, "read_patient", pid)
        return self._view(s, self.patients[pid])

    def list_triage(self, s: auth.Session) -> list[dict]:
        """Every patient this role may see now (consent checked per patient), highest risk first."""
        rbac.require(s.role, "list_triage")
        rows = []
        for pid in self.patients:
            ok, _ = self.consents.check(pid, s.role, rbac.HI_TYPE.get(s.role, "Observation"))
            if ok:
                rows.append(self._view(s, self.patients[pid]))
        self.audit.append("list_triage", actor=s.username, role=s.role, shown=len(rows))
        order = {"purple": 4, "red": 3, "amber": 2, "green": 1}
        return sorted(rows, key=lambda r: (order.get(r.get("level"), 0), r.get("risk") or 0), reverse=True)

    # ------------------------------------------------------------------ doctor and lab
    def order_kidney_test(self, s: auth.Session, pid: str, reason: str = "red alert") -> int:
        self._authorize(s, "order_test", pid)
        tid = repo.add_task(self.con, pid, s.username, reason)
        self.audit.append("task_created", actor=s.username, subject=pid, task_id=tid, kind="home_kidney_test")
        return tid

    def list_tasks(self, s: auth.Session, status: str | None = None) -> list[dict]:
        rbac.require(s.role, "list_tasks")
        out = []
        for t in repo.tasks(self.con, status=status):
            ok, _ = self.consents.check(t["patient_id"], s.role, rbac.HI_TYPE["lab"])
            if ok:
                out.append(t)
        self.audit.append("list_tasks", actor=s.username, role=s.role, shown=len(out))
        return out

    def record_lab_result(self, s: auth.Session, task_id: int, creatinine: float | None,
                          potassium: float | None = None) -> dict:
        task = next((t for t in repo.tasks(self.con) if t["task_id"] == task_id), None)
        if task is None:
            raise rbac.AccessDenied("unknown_task")
        self._authorize(s, "record_result", task["patient_id"])
        rec = self.patients[task["patient_id"]]
        reasons, flag = [], "no_aki"
        if creatinine is not None:
            ok, why = self.gate.check({"readings": {"creatinine_mg_dl": creatinine}, "ts": "", "nonce": "lab"})
            if any(r.startswith("implausible") for r in why):
                raise ValueError("implausible creatinine value")
            base = rec["cr_baseline"]
            # the shared KDIGO function: the baseline value 24 h before the new lab (rise and ratio rules)
            stage = kdigo_stage([0.0, 24.0], [base, creatinine], 1, baseline=base)
            flag = f"kdigo_stage_{stage}" if stage else "no_aki"
            cot = gr.aki_flag_with_secretion_inhibitor(stage > 0, rec.get("generics", []))
            if cot["note_key"]:
                reasons.append(cot["note_key"])
        k = gr.potassium_rule(potassium)
        if k["message_key"]:
            reasons.append(k["message_key"])
        repo.record_result(self.con, task_id, creatinine, potassium, s.username, flag)
        egfr = (egfr_ckd_epi_2021(creatinine, rec["age"], rec["female"]) if creatinine else None)
        self.audit.append("lab_result", actor=s.username, subject=task["patient_id"], task_id=task_id, flag=flag,
                          potassium_actions=k["actions"])
        return {"task_id": task_id, "flag": flag, "egfr": egfr, "egfr_tag_key": "egfr.not_reliable" if flag != "no_aki"
                else None, "notes": reasons, "potassium_actions": k["actions"]}

    # ------------------------------------------------------------------ check-ins and red flags
    def submit_checkin(self, s: auth.Session, pid: str, language: str = "en", fields: dict | None = None,
                       text: str | None = None) -> dict:
        self._authorize(s, "checkin", pid)
        capture = dict(fields or {})
        if text:
            capture.update({k: v for k, v in red_flags.parse_text(text, language).items() if v not in (None, [])})
        res = red_flags.evaluate(capture, language, audit=self.audit, patient_id=pid, actor=s.username)
        repo.add_checkin(self.con, pid, s.username, s.role, language, capture, text, res.level)
        if res.level in ("emergency", "urgent"):
            self._notify(pid, res.level, "red_flag", f"notify.redflag_{res.level}", ", ".join(res.flags),
                         source=f"{s.role} check-in")
        return {"level": res.level, "flags": res.flags, "title": res.title, "body": res.body, "call": res.call,
                "show_risk": res.show_risk, "notes": res.notes, "parsed": capture,
                "minimum_alert_level": "red" if res.level == "urgent" else None}

    # ------------------------------------------------------------------ consent
    def consent_summary(self, s: auth.Session, pid: str) -> list[dict]:
        if s.role == "patient" and s.subject == pid or s.role in ("doctor", "admin"):
            return self.consents.summary(pid)
        raise rbac.AccessDenied("not_your_record")

    def revoke_consent(self, s: auth.Session, pid: str, requester: str | None = None) -> list[str]:
        self._authorize(s, "manage_consent", pid)
        done = self.consents.revoke(pid, requester)
        self.audit.append("consent_revoked", actor=s.username, subject=pid, requester=requester or "all",
                          artefacts=[a.consent_id for a in done])
        return [a.consent_id for a in done]

    def grant_consent(self, s: auth.Session, pid: str, requester: str) -> str:
        self._authorize(s, "manage_consent", pid)
        a = self.consents.grant(pid, requester)
        self.audit.append("consent_granted", actor=s.username, subject=pid, requester=requester,
                          consent_id=a.consent_id)
        return a.consent_id

    # ------------------------------------------------------------------ interoperability
    def export_fhir(self, s: auth.Session, pid: str) -> dict:
        self._authorize(s, "export_fhir", pid)
        rec = self.patients[pid]
        obs = [("egfr", rec["egfr_baseline"], f"{load_yaml('cohort')['season']['start']}T08:00:00+05:30")]
        for t in repo.tasks(self.con, pid):
            if t["creatinine_mg_dl"] is not None:
                obs.append(("creatinine_mg_dl", t["creatinine_mg_dl"], t["resulted_at"]))
            if t["potassium_mmol_l"] is not None:
                obs.append(("potassium_mmol_l", t["potassium_mmol_l"], t["resulted_at"]))
        method = ("VrikkaTwin twin 72-hour simulation" if rec["risk_basis"] == "twin_simulation"
                  else "VrikkaTwin fast clock, hybrid model M (frozen Part 4)")
        consent = self.consents.get(pid, s.role) if s.role != "patient" else None
        bundle = fhir_export.export_bundle({"patient_id": pid, "female": rec.get("female"), "age": rec.get("age"),
                                            "observations": obs, "risk": rec.get("risk"), "level": rec.get("level"),
                                            "reasons": rec.get("reasons", []), "method": method}, consent)
        self.audit.append("fhir_export", actor=s.username, subject=pid, resources=len(bundle["entry"]))
        return bundle

    # ------------------------------------------------------------------ devices and audit
    def ingest_device(self, msg: dict) -> dict:
        return self.gate.ingest(msg)

    def audit_status(self, s: auth.Session) -> dict:
        rbac.require(s.role, "view_audit")
        self.audit.checkpoint()
        st = self.audit.verify_checkpoints()
        self.audit.append("audit_verified", actor=s.username, ok=st["ok"])
        return {**st, "records": len(self.audit.records), "public_key": self.audit.public_key}

    # ------------------------------------------------------------------ alerts (notifications)
    def _recipients(self, pid: str) -> list[str]:
        """The patient always; the doctor and family only while their consent artefact is GRANTED."""
        out = ["patient"]
        for role in ("doctor", "family"):
            ok, _ = self.consents.check(pid, role, rbac.HI_TYPE[role])
            if ok:
                out.append(role)
        return out

    def _notify(self, pid: str, level: str, kind: str, message_key: str, detail: str = "",
                source: str = "system", to: tuple[str, ...] | None = None) -> list[str]:
        sent = [r for r in self._recipients(pid) if to is None or r in to]
        for r in sent:
            repo.add_notification(self.con, pid, r, level, kind, message_key, detail, source)
        self.audit.append("alert_sent", subject=pid, level=level, kind=kind, recipients=sent, source=source)
        return sent

    def send_risk_alerts(self) -> int:
        """Today's risk levels: red -> patient, family and doctor; amber -> patient and family (self-care)."""
        n = 0
        for pid, rec in self.patients.items():
            if rec.get("level") == "red":
                self._notify(pid, "red", "risk_alert", "notify.risk_red", rec.get("risk_text", ""), "fast clock")
                n += 1
            elif rec.get("level") == "amber":
                self._notify(pid, "amber", "risk_alert", "notify.risk_amber", rec.get("risk_text", ""), "fast clock",
                             to=("patient", "family"))
                n += 1
        return n

    def inbox(self, s: auth.Session, unread_only: bool = False) -> list[dict]:
        """Alerts for the logged-in person: the doctor sees every consented patient, patient / family their own."""
        rbac.require(s.role, "read_notifications")
        if s.role == "doctor":
            rows = [r for r in repo.notifications(self.con, "doctor")
                    if self.consents.check(r["patient_id"], "doctor", rbac.HI_TYPE["doctor"])[0]]
        else:
            rows = repo.notifications(self.con, s.role, s.subject)
        if unread_only:
            rows = [r for r in rows if not r["read"]]
        for r in rows:
            p = self.patients.get(r["patient_id"], {})
            r["patient_name"] = decrypt_text(p["name_enc"]) if p.get("name_enc") else r["patient_id"]
        return rows

    def mark_read(self, s: auth.Session, notif_ids: list[int]) -> None:
        rbac.require(s.role, "read_notifications")
        mine = {r["notif_id"] for r in self.inbox(s)}
        repo.mark_read(self.con, [i for i in notif_ids if i in mine])

    def call_ambulance(self, s: auth.Session, pid: str) -> dict:
        """Emergency button: logs the call and alerts the doctor and family at once; the phone dials 108."""
        self._authorize(s, "call_ambulance", pid)
        call = load_yaml("red_flags")["flags"]["heatstroke_emergency"]["call"]
        sent = self._notify(pid, "emergency", "ambulance", "notify.ambulance", f"pressed by {s.role}",
                            source=f"{s.role} emergency button")
        self.audit.append("ambulance_called", actor=s.username, subject=pid, role=s.role, numbers=call)
        return {"numbers": call, "dial": call.split("/")[0].strip(), "notified": sent}

    # ------------------------------------------------------------------ daily medicines
    @staticmethod
    def resolve_medicine(name: str) -> dict:
        """Brand or generic -> generics and classes from config/drugs_india.yaml (unknown names are kept, flagged)."""
        lex = load_yaml("drugs_india")
        key = name.strip().lower().replace("-", "_").replace(" ", "_")
        if key in lex["brands"]:
            gens = list(lex["brands"][key]["generics"])
        elif key in lex["generics"]:
            gens = [key]
        else:
            return {"generics": [], "classes": [], "recognised": False}
        return {"generics": gens, "classes": sorted({lex["generics"][g] for g in gens if g in lex["generics"]}),
                "recognised": True}

    def _medicines(self, pid: str) -> list[dict]:
        if pid not in self._meds_seeded:                  # first use: start from the EHR medicine list
            self._meds_seeded.add(pid)
            if not repo.medicines(self.con, pid, active_only=False):
                for g in self.patients[pid].get("generics", []):
                    repo.add_medicine(self.con, pid, g, [g], None, None, "EHR")
        return repo.medicines(self.con, pid)

    def _sync_generics(self, pid: str) -> list[str]:
        gens = sorted({g for m in repo.medicines(self.con, pid) for g in m["generics"]})
        self.patients[pid]["generics"] = gens
        return gens

    def list_medicines(self, s: auth.Session, pid: str) -> list[dict]:
        self._authorize(s, "read_patient", pid)
        return self._medicines(pid)

    def add_medicine(self, s: auth.Session, pid: str, name: str, dose: str | None = None,
                     times_per_day: int | None = None) -> dict:
        self._authorize(s, "manage_medicines", pid)
        if not name or not name.strip():
            raise ValueError("medicine name is empty")
        self._medicines(pid)
        r = self.resolve_medicine(name)
        mid = repo.add_medicine(self.con, pid, name.strip(), r["generics"], dose or None, times_per_day, s.username)
        gens = self._sync_generics(pid)
        self.audit.append("medicine_added", actor=s.username, subject=pid, medicine=name.strip(),
                          generics=r["generics"], recognised=r["recognised"])
        lex = load_yaml("drugs_india")["generics"]
        classes = {lex.get(g) for g in gens}
        warnings = []
        if classes & RAS and classes & DIURETIC and classes & NSAID and set(r["classes"]) & (RAS | DIURETIC | NSAID):
            warnings.append("notify.triple_whammy")
            self._notify(pid, "red", "medicine", "notify.triple_whammy", name.strip(), source=f"{s.role} medicine list")
        return {"med_id": mid, **r, "warnings": warnings}

    def stop_medicine(self, s: auth.Session, pid: str, med_id: int) -> None:
        self._authorize(s, "manage_medicines", pid)
        if med_id not in {m["med_id"] for m in self._medicines(pid)}:
            raise rbac.AccessDenied("unknown_medicine")
        repo.stop_medicine(self.con, med_id)
        self._sync_generics(pid)
        self.audit.append("medicine_stopped", actor=s.username, subject=pid, med_id=med_id)
