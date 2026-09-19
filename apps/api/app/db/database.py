import sqlite3
import json
from threading import RLock

from app.db.models import SCHEMA
from app.models.call import AgentEvent, Call, CallStatus
from app.models.lead import Lead, utc_now


class Database:
    """Single-process local store. Agent mutations share this reentrant lock."""

    def __init__(self, url: str):
        if not url.startswith("sqlite:///"):
            raise ValueError("Local foundation supports sqlite:/// URLs only")
        self.lock = RLock()
        self.connection = sqlite3.connect(url.removeprefix("sqlite:///"), check_same_thread=False)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def get_lead(self, lead_id: str) -> Lead:
        with self.lock:
            row = self.connection.execute("SELECT data FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
        if row is None:
            raise KeyError(f"Lead {lead_id} not found")
        return Lead.model_validate_json(row[0])

    def create_lead(self, lead: Lead) -> Lead:
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO leads VALUES (?, ?)", (lead.lead_id, lead.model_dump_json()))
        return lead

    def list_leads(self) -> list[Lead]:
        with self.lock:
            rows = self.connection.execute("SELECT data FROM leads ORDER BY lead_id").fetchall()
        return [Lead.model_validate_json(row[0]) for row in rows]

    def get_call(self, call_id: str) -> Call:
        with self.lock:
            row = self.connection.execute("SELECT data FROM calls WHERE call_id=?", (call_id,)).fetchone()
        if row is None:
            raise KeyError(f"Call {call_id} not found")
        return Call.model_validate_json(row[0])

    def active_call(self, lead_id: str) -> Call | None:
        with self.lock:
            rows = self.connection.execute("SELECT data FROM calls WHERE lead_id=?", (lead_id,)).fetchall()
        for row in rows:
            call = Call.model_validate_json(row[0])
            if call.status not in {CallStatus.COMPLETED, CallStatus.ENDED, CallStatus.HANDOFF, CallStatus.BLOCKED_DNC}:
                return call
        return None

    def save_session(self, call: Call, lead: Lead | None = None) -> None:
        with self.lock, self.connection:
            row = self.connection.execute("SELECT data FROM calls WHERE call_id=?", (call.call_id,)).fetchone()
            old = Call.model_validate_json(row[0]) if row else None
            self._record_changes(call, old)
            self.connection.execute(
                "INSERT INTO calls VALUES (?, ?, ?) ON CONFLICT(call_id) DO UPDATE SET data=excluded.data",
                (call.call_id, call.lead_id, call.model_dump_json()),
            )
            if lead is not None:
                self.connection.execute("UPDATE leads SET data=? WHERE lead_id=?",
                                        (lead.model_dump_json(), lead.lead_id))
            for index, entry in enumerate(call.transcript):
                self.connection.execute("INSERT OR REPLACE INTO call_messages VALUES (?, ?, ?)",
                                        (call.call_id, index, entry.model_dump_json()))
            self.connection.execute("DELETE FROM collected_fields WHERE call_id=?", (call.call_id,))
            for field, value in call.collected_fields.items():
                self.connection.execute("INSERT INTO collected_fields VALUES (?, ?, ?)",
                                        (call.call_id, field, json.dumps(value)))
            if call.escalation:
                self.connection.execute("INSERT OR REPLACE INTO handoffs VALUES (?, ?, ?)",
                                        (call.escalation.handoff_id, call.call_id, call.escalation.model_dump_json()))
            for index, event in enumerate(call.events):
                self.connection.execute("INSERT OR REPLACE INTO events VALUES (?, ?, ?)",
                                        (call.call_id, index, event.model_dump_json()))

    @staticmethod
    def _record_changes(call: Call, old: Call | None) -> None:
        def emit(event_type, **metadata):
            call.events.append(AgentEvent(call_id=call.call_id, lead_id=call.lead_id,
                                           event_type=event_type, metadata=metadata))
        if old is None:
            emit("DNC_BLOCKED" if call.status == CallStatus.BLOCKED_DNC else "CALL_STARTED")
            if call.status == CallStatus.CONSENT_REQUIRED:
                emit("CONSENT_REQUESTED")
        if call.consent_given and (old is None or not old.consent_given):
            emit("CONSENT_GRANTED")
        if call.current_field and (old is None or old.current_field != call.current_field):
            emit("FIELD_REQUESTED", field=call.current_field)
        for key, value in call.collected_fields.items():
            if old and (key not in old.collected_fields or old.collected_fields[key] != value):
                emit("FIELD_CAPTURED", field=key)
                emit("FIELD_CONFIRMED", field=key, method="explicit" if old.pending_field == key else "validated")
        for key, failures in call.repeated_failures.items():
            if old and failures > old.repeated_failures.get(key, 0):
                emit("FIELD_VALIDATION_FAILED", field=key, attempts=failures)
        if old and old.status != call.status:
            if call.status == CallStatus.HANDOFF:
                emit("ESCALATION_DETECTED", reason=call.escalation.reason)
                emit("HANDOFF_STARTED", handoff_id=call.escalation.handoff_id)
            elif call.status == CallStatus.COMPLETING:
                emit("JOURNEY_SUBMITTED")
            elif call.status == CallStatus.COMPLETED:
                emit("JOURNEY_COMPLETED", submission_id=call.completion_reference)
                emit("CALL_ENDED", reason="COMPLETED")
            elif call.status == CallStatus.ENDED:
                emit("CALL_ENDED", reason=call.end_reason)

    def record_dnc(self, lead_id: str, blocked: bool) -> None:
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO dnc_checks(lead_id, blocked, timestamp) VALUES (?, ?, ?)",
                                    (lead_id, int(blocked), utc_now().isoformat()))

    def get_submission(self, submission_id: str) -> dict | None:
        with self.lock:
            row = self.connection.execute("SELECT result FROM journey_submissions WHERE submission_id=?",
                                          (submission_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def submission_payload(self, submission_id: str) -> dict | None:
        with self.lock:
            row = self.connection.execute("SELECT payload FROM journey_submissions WHERE submission_id=?",
                                          (submission_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_submission(self, submission_id: str, lead_id: str, payload: dict, result: dict) -> None:
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO journey_submissions VALUES (?, ?, ?, ?)",
                                    (submission_id, lead_id, json.dumps(payload), json.dumps(result)))

    def submissions(self) -> list[dict]:
        with self.lock:
            rows = self.connection.execute("SELECT payload, result FROM journey_submissions ORDER BY submission_id").fetchall()
        return [{"payload": json.loads(row[0]), "result": json.loads(row[1])} for row in rows]

    def is_dnc(self, lead_id: str) -> bool:
        with self.lock:
            return self.connection.execute("SELECT 1 FROM dnc WHERE lead_id=?", (lead_id,)).fetchone() is not None

    def block_contact(self, lead_id: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("INSERT OR IGNORE INTO dnc VALUES (?)", (lead_id,))

    def close(self) -> None:
        self.connection.close()
