"""Persistent, blinded and reproducible human-review study workflow."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

from . import service
from .persistence import DatabaseStatus, backup_database, connect_database, database_status

DECISIONS = {
    "confirmed",
    "partially_correct",
    "rejected",
    "cannot_determine",
    "intentional_localization",
}
EVIDENCE_LABELS = {"sufficient", "incomplete", "wrong", "absent"}
ACTIONS = {"usable", "needs_revision", "unusable"}
SEVERITIES = {"info", "low", "medium", "high", "critical"}

_STUDY_MIGRATIONS = (
    """
CREATE TABLE IF NOT EXISTS studies(
  id TEXT PRIMARY KEY, evidence_bundle_id TEXT NOT NULL, seed_hash TEXT NOT NULL,
  created_at TEXT NOT NULL, frozen INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS reviewers(
  study_id TEXT NOT NULL, reviewer TEXT NOT NULL, token_hash TEXT NOT NULL,
  PRIMARY KEY(study_id,reviewer), UNIQUE(study_id,token_hash),
  FOREIGN KEY(study_id) REFERENCES studies(id));
CREATE TABLE IF NOT EXISTS assignments(
  study_id TEXT NOT NULL, reviewer TEXT NOT NULL, sequence INTEGER NOT NULL,
  finding_id TEXT NOT NULL, blinded_json TEXT NOT NULL, opened_at TEXT,
  PRIMARY KEY(study_id, reviewer, finding_id), UNIQUE(study_id, reviewer, sequence),
  FOREIGN KEY(study_id) REFERENCES studies(id));
CREATE TABLE IF NOT EXISTS decisions(
  study_id TEXT NOT NULL, reviewer TEXT NOT NULL, finding_id TEXT NOT NULL,
  decision TEXT NOT NULL, rationale TEXT NOT NULL, evidence_quality TEXT NOT NULL,
  severity_assessment TEXT NOT NULL, usefulness INTEGER NOT NULL,
  actionability TEXT NOT NULL, seconds_spent INTEGER NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(study_id, reviewer,finding_id),
  FOREIGN KEY(study_id,reviewer,finding_id) REFERENCES assignments(study_id,reviewer,finding_id));
""",
)


class ReviewStudy:
    def __init__(self, path: Path):
        self.connection = connect_database(path, kind="review-study", migrations=_STUDY_MIGRATIONS)

    def close(self) -> None:
        self.connection.close()

    def status(self) -> DatabaseStatus:
        return database_status(self.connection, kind="review-study")

    def backup(self, destination: Path) -> None:
        backup_database(self.connection, destination)

    def __enter__(self) -> ReviewStudy:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def initialize(
        self, evidence_path: Path, *, study_id: str, reviewers: tuple[str, ...], seed: str
    ) -> dict[str, str]:
        if (
            not study_id.strip()
            or not seed
            or not reviewers
            or any(not value.strip() for value in reviewers)
        ):
            raise ValueError("study id, secret seed, and reviewer pseudonyms are required")
        if len(set(reviewers)) != len(reviewers):
            raise ValueError("reviewer pseudonyms must be unique")
        document = json.loads(evidence_path.read_text("utf-8"))
        findings = document.get("findings")
        if not isinstance(findings, list) or not findings:
            raise ValueError("evidence bundle contains no findings")
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            "INSERT INTO studies VALUES (?,?,?,?,1)",
            (study_id, document["id"], hashlib.sha256(seed.encode()).hexdigest(), now),
        )
        for reviewer in reviewers:
            token = hmac.new(
                seed.encode(), f"reviewer\0{study_id}\0{reviewer}".encode(), hashlib.sha256
            ).hexdigest()
            self.connection.execute(
                "INSERT INTO reviewers VALUES (?,?,?)",
                (study_id, reviewer, hashlib.sha256(token.encode()).hexdigest()),
            )
            shuffled = list(findings)
            reviewer_seed = hashlib.sha256(f"{seed}\0{reviewer}".encode()).digest()
            # Reproducible study assignment, not security randomness.
            random.Random(reviewer_seed).shuffle(shuffled)  # nosec B311
            for sequence, finding in enumerate(shuffled, 1):
                blinded = {
                    key: finding.get(key)
                    for key in (
                        "id",
                        "finding_type",
                        "title",
                        "explanation",
                        "evidence",
                        "affected_languages",
                        "suggested_action",
                    )
                }
                # Confidence, severity, model/provider provenance, and ordering are intentionally hidden.
                self.connection.execute(
                    "INSERT INTO assignments VALUES (?,?,?,?,?,NULL)",
                    (
                        study_id,
                        reviewer,
                        sequence,
                        finding["id"],
                        json.dumps(blinded, ensure_ascii=False),
                    ),
                )
        self.connection.commit()
        return {
            reviewer: hmac.new(
                seed.encode(), f"reviewer\0{study_id}\0{reviewer}".encode(), hashlib.sha256
            ).hexdigest()
            for reviewer in reviewers
        }

    def authenticate(self, study_id: str, token: str) -> str | None:
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        row = self.connection.execute(
            "SELECT reviewer,token_hash FROM reviewers WHERE study_id=? AND token_hash=?",
            (study_id, digest),
        ).fetchone()
        return row[0] if row and hmac.compare_digest(row[1], digest) else None

    def progress(self, study_id: str, reviewer: str) -> dict[str, int]:
        total = self.connection.execute(
            "SELECT COUNT(*) FROM assignments WHERE study_id=? AND reviewer=?", (study_id, reviewer)
        ).fetchone()[0]
        completed = self.connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE study_id=? AND reviewer=?", (study_id, reviewer)
        ).fetchone()[0]
        return {"completed": completed, "total": total, "remaining": total - completed}

    def next_assignment(self, study_id: str, reviewer: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT a.sequence,a.finding_id,a.blinded_json,a.opened_at
          FROM assignments a LEFT JOIN decisions d ON d.study_id=a.study_id AND d.reviewer=a.reviewer
          AND d.finding_id=a.finding_id WHERE a.study_id=? AND a.reviewer=? AND d.finding_id IS NULL
          ORDER BY a.sequence LIMIT 1""",
            (study_id, reviewer),
        ).fetchone()
        if row is None:
            return None
        opened = row[3] or datetime.now(UTC).isoformat()
        if row[3] is None:
            self.connection.execute(
                "UPDATE assignments SET opened_at=? WHERE study_id=? AND reviewer=? AND finding_id=?",
                (opened, study_id, reviewer, row[1]),
            )
            self.connection.commit()
        return {
            "sequence": row[0],
            "finding_id": row[1],
            "opened_at": opened,
            "finding": json.loads(row[2]),
        }

    def record(
        self,
        study_id: str,
        reviewer: str,
        finding_id: str,
        *,
        decision: str,
        rationale: str,
        evidence_quality: str,
        severity_assessment: str,
        usefulness: int,
        actionability: str,
        seconds_spent: int,
    ) -> None:
        if decision not in DECISIONS or evidence_quality not in EVIDENCE_LABELS:
            raise ValueError("invalid decision or evidence-quality label")
        if severity_assessment not in SEVERITIES or actionability not in ACTIONS:
            raise ValueError("invalid severity or actionability label")
        if not rationale.strip() or not 1 <= usefulness <= 5 or seconds_spent < 0:
            raise ValueError("rationale, usefulness 1..5, and non-negative time are required")
        assignment = self.connection.execute(
            "SELECT opened_at FROM assignments WHERE study_id=? AND reviewer=? AND finding_id=?",
            (study_id, reviewer, finding_id),
        ).fetchone()
        if assignment is None or assignment[0] is None:
            raise ValueError("assignment must be opened by this reviewer before recording")
        self.connection.execute(
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                study_id,
                reviewer,
                finding_id,
                decision,
                rationale,
                evidence_quality,
                severity_assessment,
                usefulness,
                actionability,
                seconds_spent,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.commit()

    def export(self, study_id: str, destination: Path) -> None:
        study = self.connection.execute(
            "SELECT id,evidence_bundle_id,seed_hash,created_at,frozen FROM studies WHERE id=?",
            (study_id,),
        ).fetchone()
        if study is None:
            raise ValueError("unknown review study")
        columns = (
            "reviewer",
            "finding_id",
            "decision",
            "rationale",
            "evidence_quality",
            "severity_assessment",
            "usefulness",
            "actionability",
            "seconds_spent",
            "created_at",
        )
        rows = self.connection.execute(
            """SELECT reviewer,finding_id,decision,rationale,evidence_quality,
            severity_assessment,usefulness,actionability,seconds_spent,created_at
            FROM decisions WHERE study_id=? ORDER BY reviewer,finding_id""",
            (study_id,),
        ).fetchall()
        payload = {
            "schema_version": "1.0",
            "study": {
                "id": study[0],
                "evidence_bundle_id": study[1],
                "seed_hash": study[2],
                "created_at": study[3],
                "frozen": bool(study[4]),
            },
            "decisions": [dict(zip(columns, row, strict=False)) for row in rows],
        }
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


_REVIEW_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Blinded course finding review</title>
<style>body{font:16px system-ui;max-width:900px;margin:auto;padding:2rem;color:#17202a}fieldset{border:1px solid #bbc;padding:1rem;margin:1rem 0}label{display:block;margin:.7rem 0}textarea{width:100%;min-height:7rem}pre{white-space:pre-wrap;background:#f5f7f8;padding:1rem}button{padding:.6rem 1rem}.error{color:#a00}.muted{color:#566}</style>
<h1>Blinded course finding review</h1><p id="progress" class="muted"></p><main id="finding"></main><form id="form" hidden><fieldset><legend>Your independent judgment</legend>
<label>Decision <select name="decision" required><option value="">Choose…</option><option>confirmed</option><option>partially_correct</option><option>rejected</option><option>cannot_determine</option>
<option>intentional_localization</option></select></label>
<label>Evidence quality <select name="evidence_quality" required><option value="">Choose…</option><option>sufficient</option><option>incomplete</option><option>wrong</option><option>absent</option></select></label>
<label>Severity <select name="severity_assessment" required><option value="">Choose…</option><option>info</option><option>low</option><option>medium</option><option>high</option><option>critical</option></select></label>
<label>Editorial usefulness (1-5) <input name="usefulness" type="number" min="1" max="5" required></label>
<label>Proposed action <select name="actionability" required><option value="">Choose…</option><option>usable</option><option>needs_revision</option><option>unusable</option></select></label>
<label>Rationale <textarea name="rationale" required></textarea></label>
<button>Record and continue</button></fieldset></form><p id="message" role="status"></p>
<script>const token=sessionStorage.getItem('eii-review-token')||prompt('Reviewer token');if(token)sessionStorage.setItem('eii-review-token',token);let current=null;const headers={'Authorization':'Bearer '+token};function node(tag,text){const x=document.createElement(tag);x.textContent=text;return x}
async function load(){const r=await fetch('/api/next',{headers});if(!r.ok){message.textContent='Access denied or study unavailable.';return}
const d=await r.json();progress.textContent=d.progress.completed+' of '+d.progress.total+' completed';finding.replaceChildren();
if(!d.assignment){finding.append(node('h2','Review complete'));form.hidden=true;return}current=d.assignment;
finding.append(node('h2',current.finding.title));finding.append(node('p',current.finding.explanation));
for(const e of current.finding.evidence||[]){finding.append(node('pre',(e.block_id||'evidence')+'\n'+(e.excerpt||'Evidence absent')))}form.hidden=false}
form.onsubmit=async e=>{e.preventDefault();const v=Object.fromEntries(new FormData(form));v.finding_id=current.finding_id;
v.usefulness=Number(v.usefulness);const r=await fetch('/api/decision',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(v)});
if(!r.ok){message.textContent=(await r.json()).error||'Could not record decision';return}form.reset();message.textContent='Decision recorded.';await load()};load();</script></html>"""


def _review_page() -> tuple[bytes, str]:
    nonce = secrets.token_urlsafe(24)
    page = _REVIEW_PAGE.replace("<style>", f'<style nonce="{nonce}">').replace(
        "<script>", f'<script nonce="{nonce}">'
    )
    return page.encode(), (
        "default-src 'none'; "
        f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )


def make_study_handler(
    database: Path,
    study_id: str,
    *,
    metrics: service.ServiceMetrics | None = None,
    audit_sink: service.AuditSink | None = None,
) -> type[service.ObservableHandler]:
    service_metrics = metrics or service.ServiceMetrics()

    class Handler(service.ObservableHandler):
        metrics_registry = service_metrics

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                getattr(self, "_page_csp", "default-src 'none'; frame-ancestors 'none'"),
            )
            super().end_headers()

        def _reviewer(self) -> str | None:
            authorization = self.headers.get("Authorization", "")
            token = authorization[7:] if authorization.startswith("Bearer ") else ""
            with ReviewStudy(database) as study:
                return study.authenticate(study_id, token)

        def _json(self, status: int, value: object) -> None:
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/metrics":
                self.send_metrics()
                return
            if path == "/readyz":
                try:
                    with ReviewStudy(database) as study:
                        status = study.status()
                    self._json(200, {"status": "ready", "database_schema": status.schema_version})
                except Exception as error:
                    self._json(503, {"status": "not-ready", "detail": str(error)})
                return
            if path == "/":
                body, self._page_csp = _review_page()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path != "/api/next":
                self.send_error(404)
                return
            reviewer = self._reviewer()
            if reviewer is None:
                self._json(401, {"error": "invalid reviewer token"})
                return
            with ReviewStudy(database) as study:
                assignment = study.next_assignment(study_id, reviewer)
                progress = study.progress(study_id, reviewer)
            self._json(200, {"assignment": assignment, "progress": progress})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/decision":
                self.send_error(404)
                return
            reviewer = self._reviewer()
            if reviewer is None:
                self._json(401, {"error": "invalid reviewer token"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self._json(415, {"error": "Content-Type must be application/json"})
                return
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                self._json(403, {"error": "cross-origin request rejected"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 16_384:
                    raise ValueError("invalid request size")
                data = json.loads(self.rfile.read(length))
                finding_id = str(data.pop("finding_id"))
                with ReviewStudy(database) as study:
                    opened = study.connection.execute(
                        "SELECT opened_at FROM assignments WHERE study_id=? AND reviewer=? AND finding_id=?",
                        (study_id, reviewer, finding_id),
                    ).fetchone()
                    if opened is None:
                        raise ValueError("assignment does not belong to this reviewer")
                    opened_at = opened[0]
                    if opened_at is None:
                        raise ValueError("assignment was not opened")
                    seconds = max(
                        0,
                        round(
                            (datetime.now(UTC) - datetime.fromisoformat(opened_at)).total_seconds()
                        ),
                    )
                    study.record(study_id, reviewer, finding_id, seconds_spent=seconds, **data)
                self._json(201, {"recorded": True})
            except (
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
                sqlite3.IntegrityError,
            ) as error:
                self._json(400, {"error": str(error)})

        def log_message(self, format: str, *args: object) -> None:
            pass

    Handler.audit_emitter = audit_sink
    return Handler


def serve_study(
    database: Path,
    study_id: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8090,
    audit_stream: TextIO | None = None,
) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(
            "review study server is loopback-only; use an authenticated TLS proxy for remote review"
        )
    sink = service.json_audit_sink(audit_stream) if audit_stream else None
    with service.HardenedThreadingHTTPServer(
        (host, port), make_study_handler(database, study_id, audit_sink=sink)
    ) as server:
        server.serve_forever()
