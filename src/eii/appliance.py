from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TextIO
from urllib.parse import urlparse

from .adapters import PlctExportAdapter, RepositoryAdapter
from .appliance_health_handlers import health_handler, metrics_handler, readiness_handler
from .appliance_package import create_package as create_package
from .appliance_package import verify_package as verify_package
from .appliance_router import ApplianceRouter
from .appliance_state import active_release, read_config
from .appliance_state import configure as configure
from .appliance_state import recover_active_release as recover_active_release
from .appliance_state import rollback as rollback
from .appliance_state import write_onboarding_page as write_onboarding_page
from .appliance_trust import apply_trust_rotation as apply_trust_rotation
from .appliance_trust import create_trust_rotation as create_trust_rotation
from .appliance_trust import initialize_trust as initialize_trust
from .appliance_trust import install_trusted_package as install_trusted_package
from .appliance_types import ApplianceConfig, CapabilityReport, PackageManifest
from .crypto import crypto_self_test, sign_ed25519, verify_ed25519
from .crypto import public_key_fingerprint as _public_key_fingerprint
from .domain import CourseRelease
from .evidence_handlers import register_evidence_routes
from .models import OpenAICompatibleClient
from .safety_handlers import register_safety_routes
from .safety_verification import verify_safety_case_document
from .service import (
    AuditSink,
    HardenedThreadingHTTPServer,
    ObservableHandler,
    ServiceMetrics,
    json_audit_sink,
)
from .service_limits import BoundedRateLimiter
from .tutor import GroundedTutor
from .weather_handlers import register_weather_routes


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


def public_key_fingerprint(public_key: Path) -> str:
    return _public_key_fingerprint(public_key)


def _ed25519_sign(data: bytes, private_key: Path | None) -> str:
    return sign_ed25519(data, private_key)


def _ed25519_verify(data: bytes, signature: str, public_key: Path | None) -> bool:
    return verify_ed25519(data, signature, public_key)


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
    router = ApplianceRouter()
    router.add("GET", "/metrics", metrics_handler)
    router.add("GET", "/readyz", readiness_handler(appliance_root, draining))
    router.add("GET", "/healthz", health_handler(appliance_root))
    register_evidence_routes(router, appliance_root)
    register_weather_routes(router, appliance_root)
    register_safety_routes(
        router,
        tutor=tutor,
        course=course,
        config=config,
        query_token=query_token,
        rate_limiter=rate_limiter,
        capacity=query_capacity,
    )

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
            router.dispatch(self, "GET", urlparse(self.path).path)

        def do_POST(self) -> None:
            router.dispatch(self, "POST", urlparse(self.path).path)

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
    crypto_self_test()
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
