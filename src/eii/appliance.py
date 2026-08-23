from __future__ import annotations

import hmac
import json
import mimetypes
import os
import platform
import shutil
import signal
import tempfile
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TextIO, cast
from urllib.parse import unquote, urlparse

from .adapters import PlctExportAdapter, RepositoryAdapter
from .appliance_package import create_package as create_package
from .appliance_package import verify_package as verify_package
from .appliance_state import active_release, read_config
from .appliance_state import atomic_json as _atomic_json
from .appliance_state import configure as configure
from .appliance_state import recover_active_release as recover_active_release
from .appliance_state import rollback as rollback
from .appliance_state import write_onboarding_page as write_onboarding_page
from .appliance_types import ApplianceConfig, CapabilityReport, PackageManifest
from .crypto import public_key_fingerprint as _public_key_fingerprint
from .crypto import sign_ed25519, verify_ed25519
from .domain import CourseRelease, to_dict
from .models import OpenAICompatibleClient
from .safety_types import AssistantResponse
from .safety_verification import verify_safety_case_document
from .service import (
    AuditSink,
    HardenedThreadingHTTPServer,
    ObservableHandler,
    ServiceMetrics,
    json_audit_sink,
)
from .service_limits import BoundedRateLimiter, nonce_html
from .tutor import GroundedTutor


def capability_check(
    path: Path = Path("."),
    *,
    minimum_memory_bytes: int = 8 * 1024**3,
    minimum_disk_bytes: int = 20 * 1024**3,
) -> CapabilityReport:
    memory = None
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text("utf-8").splitlines():
            if line.startswith("MemTotal:"):
                memory = int(line.split()[1]) * 1024
                break
    free = shutil.disk_usage(path.resolve()).free
    cpu_count = os.cpu_count() or 1
    reasons = []
    if memory is not None and memory < minimum_memory_bytes:
        reasons.append(f"memory below {minimum_memory_bytes} bytes")
    if free < minimum_disk_bytes:
        reasons.append(f"free disk below {minimum_disk_bytes} bytes")
    if cpu_count < 4:
        reasons.append("fewer than 4 logical CPUs")
    profile = "large-local" if memory and memory >= 32 * 1024**3 else "small-local"
    return CapabilityReport(
        platform.machine(), cpu_count, memory, free, profile, not reasons, tuple(reasons)
    )


def install_package(
    package: Path,
    appliance_root: Path,
    *,
    public_key: Path,
    safety_public_key: Path | None = None,
    trusted_reviewer_fingerprints: frozenset[str] = frozenset(),
) -> PackageManifest:
    manifest = verify_package(package, public_key=public_key)
    existing_pointer = appliance_root / "active.json"
    safety_case = None
    assistant_enabled = any(
        key in manifest.metadata for key in ("safety_case_path", "course_path", "model")
    )
    if existing_pointer.exists() or assistant_enabled:
        safety_path = manifest.metadata.get("safety_case_path")
        if not safety_path or safety_path not in manifest.files:
            raise ValueError("updates require an embedded approved offline safety case")
        with zipfile.ZipFile(package) as archive:
            safety_case = json.loads(archive.read(str(safety_path)))
        if safety_public_key is None:
            raise ValueError("updates require a trusted safety evaluator public key")
        verify_safety_case_document(
            safety_case,
            public_key=safety_public_key,
            trusted_reviewer_fingerprints=trusted_reviewer_fingerprints,
        )
        if manifest.metadata.get("safety_case_id") != safety_case["id"]:
            raise ValueError("package metadata is not bound to its safety case id")
        if not manifest.metadata.get("course_path") or not manifest.metadata.get("model"):
            raise ValueError("safety-gated updates require canonical course and model metadata")
        if manifest.metadata.get("prompt_version") != safety_case["prompt_version"]:
            raise ValueError("packaged prompt version differs from the evaluated prompt")
        evaluated_models = {case["response"]["model_run"]["model"] for case in safety_case["cases"]}
        if evaluated_models != {manifest.metadata["model"]}:
            raise ValueError("packaged model differs from the evaluated assistant model")
    releases = appliance_root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    final = releases / manifest.package_id
    if final.exists():
        raise ValueError(f"package is already installed: {manifest.package_id}")
    staging = releases / f".staging-{manifest.package_id}"
    staging.mkdir()
    try:
        with zipfile.ZipFile(package) as archive:
            for name in (*manifest.files.keys(), "manifest.json", "manifest.signature"):
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        if safety_case is not None:
            course_relative = PurePosixPath(str(manifest.metadata["course_path"]))
            if course_relative.is_absolute() or ".." in course_relative.parts:
                raise ValueError("unsafe canonical course path in package metadata")
            course_source = staging.joinpath(*course_relative.parts)
            adapter = next(
                (
                    item
                    for item in (PlctExportAdapter(), RepositoryAdapter())
                    if item.can_load(course_source)
                ),
                None,
            )
            if adapter is None:
                raise ValueError("evaluated packaged course cannot be loaded canonically")
            language_value = manifest.metadata.get("language")
            packaged_course = adapter.load(
                course_source, language=str(language_value) if language_value is not None else None
            )
            if packaged_course.hash != safety_case["course_hash"]:
                raise ValueError("packaged course hash differs from the evaluated course release")
            assert safety_public_key is not None
            verify_safety_case_document(
                safety_case,
                public_key=safety_public_key,
                course=packaged_course,
                trusted_reviewer_fingerprints=trusted_reviewer_fingerprints,
            )
        os.replace(staging, final)
        pointer_tmp = appliance_root / ".active.json.tmp"
        previous = (
            json.loads(existing_pointer.read_text("utf-8")) if existing_pointer.exists() else None
        )
        pointer = {"package_id": manifest.package_id, "version": manifest.version}
        pointer_tmp.write_text(json.dumps(pointer) + "\n", "utf-8")
        os.replace(pointer_tmp, appliance_root / "active.json")
        with (appliance_root / "activation-history.jsonl").open("a", encoding="utf-8") as history:
            history.write(
                json.dumps(
                    {
                        "activated_at": datetime.now(UTC).isoformat(),
                        "previous": previous,
                        "current": pointer,
                    }
                )
                + "\n"
            )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest


def _ed25519_sign(data: bytes, private_key: Path | None) -> str:
    return sign_ed25519(data, private_key)


def _ed25519_verify(data: bytes, signature: str, public_key: Path | None) -> bool:
    return verify_ed25519(data, signature, public_key)


def public_key_fingerprint(public_key: Path) -> str:
    return _public_key_fingerprint(public_key)


def initialize_trust(appliance_root: Path, public_key: Path) -> str:
    fingerprint = public_key_fingerprint(public_key)
    trust = appliance_root / "trust"
    keys = trust / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(public_key, keys / f"{fingerprint}.pem")
    state = {
        "schema_version": "1.0",
        "trusted_keys": [fingerprint],
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _atomic_json(trust / "state.json", state)
    with (trust / "history.jsonl").open("a", encoding="utf-8") as history:
        history.write(
            json.dumps(
                {"action": "initialize", "fingerprint": fingerprint, "at": state["updated_at"]}
            )
            + "\n"
        )
    return fingerprint


def create_trust_rotation(
    current_private_key: Path,
    current_public_key: Path,
    new_public_key: Path,
    destination: Path,
    *,
    revoke_old: bool = False,
) -> None:
    statement = {
        "schema_version": "1.0",
        "old_fingerprint": public_key_fingerprint(current_public_key),
        "new_fingerprint": public_key_fingerprint(new_public_key),
        "new_public_key": new_public_key.read_text("utf-8"),
        "revoke_old": revoke_old,
        "created_at": datetime.now(UTC).isoformat(),
    }
    body = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    payload = {"statement": statement, "signature": _ed25519_sign(body, current_private_key)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def apply_trust_rotation(appliance_root: Path, authorization: Path) -> str:
    trust = appliance_root / "trust"
    state_path = trust / "state.json"
    state = json.loads(state_path.read_text("utf-8"))
    payload = json.loads(authorization.read_text("utf-8"))
    statement = payload["statement"]
    old = statement["old_fingerprint"]
    if old not in state["trusted_keys"]:
        raise ValueError("rotation is not authorized by a currently trusted key")
    body = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    if not _ed25519_verify(body, payload["signature"], trust / "keys" / f"{old}.pem"):
        raise ValueError("trust rotation signature verification failed")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as candidate:
        candidate.write(statement["new_public_key"])
        candidate.flush()
        actual = public_key_fingerprint(Path(candidate.name))
    if actual != statement["new_fingerprint"]:
        raise ValueError("rotated public key fingerprint mismatch")
    new = statement["new_fingerprint"]
    (trust / "keys" / f"{new}.pem").write_text(statement["new_public_key"], "utf-8")
    trusted = (
        [new] if statement.get("revoke_old") else list(dict.fromkeys([*state["trusted_keys"], new]))
    )
    state = {
        "schema_version": "1.0",
        "trusted_keys": trusted,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _atomic_json(state_path, state)
    with (trust / "history.jsonl").open("a", encoding="utf-8") as history:
        history.write(
            json.dumps(
                {
                    "action": "rotate",
                    "old_fingerprint": old,
                    "new_fingerprint": new,
                    "revoke_old": bool(statement.get("revoke_old")),
                    "at": state["updated_at"],
                }
            )
            + "\n"
        )
    return cast(str, new)


def install_trusted_package(
    package: Path,
    appliance_root: Path,
    *,
    safety_public_key: Path | None = None,
    trusted_reviewer_fingerprints: frozenset[str] = frozenset(),
) -> PackageManifest:
    trust = appliance_root / "trust"
    state = json.loads((trust / "state.json").read_text("utf-8"))
    for fingerprint in state["trusted_keys"]:
        public_key = trust / "keys" / f"{fingerprint}.pem"
        try:
            return install_package(
                package,
                appliance_root,
                public_key=public_key,
                safety_public_key=safety_public_key,
                trusted_reviewer_fingerprints=trusted_reviewer_fingerprints,
            )
        except ValueError as error:
            if "signature verification failed" not in str(error):
                raise
    raise ValueError("package is not signed by a currently trusted publisher key")


def _capacity_answer(
    capacity: threading.BoundedSemaphore,
    tutor: GroundedTutor,
    course: CourseRelease,
    data: dict[str, object],
    behavior: str,
    language: str,
) -> AssistantResponse | None:
    if not capacity.acquire(blocking=False):
        return None
    try:
        question = cast(str, data["question"])
        return tutor.answer(
            f"Assistant behavior: {behavior}. {question}",
            course=course,
            activity_id=cast(str | None, data.get("activity_id")),
            language=language,
        )
    finally:
        capacity.release()


def make_handler(
    appliance_root: Path,
    *,
    tutor: GroundedTutor | None = None,
    course: CourseRelease | None = None,
    config: ApplianceConfig | None = None,
    max_queries_per_minute: int = 30,
    max_concurrent_queries: int = 4,
    query_token: str | None = None,
    metrics: ServiceMetrics | None = None,
    audit_sink: AuditSink | None = None,
    draining: threading.Event | None = None,
    max_rate_limit_clients: int = 4096,
) -> type[ObservableHandler]:
    if max_queries_per_minute < 1:
        raise ValueError("query rate limit must be positive")
    if max_concurrent_queries < 1:
        raise ValueError("concurrent query limit must be positive")
    if max_rate_limit_clients < 1:
        raise ValueError("rate-limit client capacity must be positive")
    rate_limiter = BoundedRateLimiter(max_queries_per_minute, max_rate_limit_clients)
    query_capacity = threading.BoundedSemaphore(max_concurrent_queries)
    service_metrics = metrics or ServiceMetrics()

    class Handler(ObservableHandler):
        metrics_registry = service_metrics
        rate_limit_state = rate_limiter.state

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            nonce = getattr(self, "_content_nonce", None)
            script_policy = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
            style_policy = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; "
                f"style-src {style_policy}; script-src {script_policy}; "
                "connect-src 'self'; frame-ancestors 'none'",
            )
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _rate_limited(self) -> bool:
            return rate_limiter.limited(self.client_address[0])

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/metrics":
                self.send_metrics()
                return
            if parsed.path == "/readyz":
                payload: dict[str, object]
                if draining and draining.is_set():
                    payload, status = {"status": "draining"}, 503
                else:
                    try:
                        release = active_release(appliance_root)
                        payload, status = {"status": "ready", "release": release.name}, 200
                    except Exception as error:
                        payload, status = {"status": "not-ready", "detail": str(error)}, 503
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/healthz":
                try:
                    release = active_release(appliance_root)
                    payload, status = (
                        {"status": "ok", "release": release.name, "offline": True},
                        200,
                    )
                except Exception as error:
                    payload, status = {"status": "error", "detail": str(error)}, 503
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            relative = unquote(parsed.path).lstrip("/") or "index.html"
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts:
                self.send_error(400)
                return
            root = active_release(appliance_root) / "content"
            target = root.joinpath(*pure.parts)
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file() or not target.resolve().is_relative_to(root.resolve()):
                self.send_error(404)
                return
            body = target.read_bytes()
            content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
            if content_type == "text/html":
                body, self._content_nonce = nonce_html(body)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/query" or tutor is None or course is None:
                self.send_error(404)
                return
            if self._rate_limited():
                self.send_error(429, "query rate limit exceeded")
                return
            if query_token is not None:
                authorization = self.headers.get("Authorization", "")
                supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
                if not supplied or not hmac.compare_digest(supplied, query_token):
                    self.send_error(401, "valid classroom bearer token required")
                    return
            try:
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    raise ValueError("Content-Type must be application/json")
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    raise ValueError("cross-origin requests are not allowed")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 32_768:
                    raise ValueError("request size must be between 1 and 32768 bytes")
                data = json.loads(self.rfile.read(length))
                if set(data) - {"question", "language", "activity_id"}:
                    raise ValueError("query contains unsupported fields")
                question = data["question"]
                if not isinstance(question, str) or not question.strip() or len(question) > 4000:
                    raise ValueError(
                        "question must be a non-empty string of at most 4000 characters"
                    )
                language = data.get("language", course.language)
                if config and language not in config.allowed_languages:
                    raise ValueError("requested language is not enabled by the teacher")
                behavior = config.assistant_behavior if config else "hint-first"
                response = _capacity_answer(query_capacity, tutor, course, data, behavior, language)
                if response is None:
                    self.send_error(503, "model query capacity exhausted")
                    return
                payload = {
                    "answer": response.answer,
                    "citations": response.citations,
                    "retrieved": [
                        {"block_id": x.block_id, "block_hash": x.block_hash, "score": x.score}
                        for x in response.retrieved
                    ],
                    "model_run": to_dict(response.model_run),
                }
                body, status = json.dumps(payload, ensure_ascii=False).encode(), 200
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                body, status = json.dumps({"error": str(error)}).encode(), 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    Handler.audit_emitter = audit_sink
    return Handler


def configured_tutor(
    appliance_root: Path,
) -> tuple[GroundedTutor | None, CourseRelease | None]:
    release = active_release(appliance_root)
    manifest = json.loads((release / "manifest.json").read_text("utf-8"))
    metadata = manifest.get("metadata", {})
    required = ("model_base_url", "model", "course_path")
    if not all(metadata.get(key) for key in required):
        return None, None
    endpoint = urlparse(str(metadata["model_base_url"]))
    if endpoint.scheme not in {"http", "https"} or endpoint.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("offline appliance model endpoint must be loopback-only")
    relative = PurePosixPath(str(metadata["course_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe configured course path")
    source = release.joinpath(*relative.parts)
    adapter = next(
        (item for item in (PlctExportAdapter(), RepositoryAdapter()) if item.can_load(source)), None
    )
    if adapter is None:
        raise ValueError("configured course has no compatible adapter")
    course = adapter.load(source, language=metadata.get("language"))
    client = OpenAICompatibleClient(
        str(metadata["model_base_url"]), str(metadata["model"]), provider="local-vllm"
    )
    return GroundedTutor(
        client, prompt_version=str(metadata.get("prompt_version", "grounded-tutor-v1"))
    ), course


def serve(
    appliance_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    query_token: str | None = None,
    audit_stream: TextIO | None = None,
    max_request_workers: int = 64,
    shutdown_grace_seconds: float = 30.0,
    max_queries_per_minute: int = 30,
    max_concurrent_queries: int = 4,
    max_rate_limit_clients: int = 4096,
) -> None:
    if shutdown_grace_seconds < 0:
        raise ValueError("shutdown grace period cannot be negative")
    tutor, course = configured_tutor(appliance_root)
    config = read_config(appliance_root)
    draining = threading.Event()
    with HardenedThreadingHTTPServer(
        (host, port),
        make_handler(
            appliance_root,
            tutor=tutor,
            course=course,
            config=config,
            query_token=query_token,
            audit_sink=(json_audit_sink(audit_stream) if audit_stream else None),
            draining=draining,
            max_queries_per_minute=max_queries_per_minute,
            max_concurrent_queries=max_concurrent_queries,
            max_rate_limit_clients=max_rate_limit_clients,
        ),
        max_request_workers=max_request_workers,
    ) as server:
        previous: dict[signal.Signals, Any] = {}

        def stop(signum: int, _frame: object) -> None:
            draining.set()
            threading.Thread(target=server.shutdown, name="eii-shutdown", daemon=True).start()

        if threading.current_thread() is threading.main_thread():
            for name in (signal.SIGTERM, signal.SIGINT):
                previous[name] = signal.getsignal(name)
                signal.signal(name, stop)
        try:
            server.serve_forever()
        finally:
            draining.set()
            server.drain(shutdown_grace_seconds)
            for name, handler in previous.items():
                signal.signal(name, handler)
