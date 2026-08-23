"""Signed, provider-hostable exchange envelope for Sentinel federation."""

from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .crypto import public_key_fingerprint, sign_ed25519, verify_ed25519
from .domain import canonical_json, to_dict
from .evidence import load_bundle

FEDERATION_VERSION = "eii-learning-assurance-envelope-v1"


def create_envelope(
    bundle_path: Path,
    destination: Path,
    *,
    private_key: Path,
    public_key: Path,
    provider_id: str | None = None,
    audit_run_id: str | None = None,
) -> dict[str, Any]:
    bundle = load_bundle(bundle_path)
    bundle_value = to_dict(bundle)
    signature = sign_ed25519(canonical_json(bundle_value).encode("utf-8"), private_key)
    envelope = {
        "bundle": bundle_value,
        "signature": signature,
        "signing_key_fingerprint": public_key_fingerprint(public_key),
        **({"provider_id": provider_id} if provider_id else {}),
        **({"audit_run_id": audit_run_id} if audit_run_id else {}),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    return envelope


def verify_envelope(path: Path, public_key: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text("utf-8"))
    required = {"bundle", "signature", "signing_key_fingerprint"}
    if (
        not isinstance(raw, dict)
        or not required.issubset(raw)
        or not set(raw).issubset(required | {"provider_id", "audit_run_id"})
    ):
        raise ValueError("federation envelope fields do not match the v1 contract")
    expected = public_key_fingerprint(public_key)
    if raw["signing_key_fingerprint"] != expected:
        raise ValueError("federation envelope signing-key fingerprint mismatch")
    if not verify_ed25519(
        canonical_json(raw["bundle"]).encode("utf-8"), raw["signature"], public_key
    ):
        raise ValueError("federation envelope signature is invalid")
    # Reuse the full canonical verifier rather than accepting a signature over
    # a malformed or internally inconsistent bundle.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        bundle_path = Path(directory) / "bundle.json"
        bundle_path.write_text(json.dumps(raw["bundle"], ensure_ascii=False), "utf-8")
        load_bundle(bundle_path)
    return cast(dict[str, Any], raw)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise HTTPError(req.full_url, code, "redirect refused", headers, fp)


def submit_envelope(
    path: Path,
    endpoint: str,
    *,
    token: str,
    institution_id: str,
    provider_id: str | None = None,
    timeout: float = 30.0,
    allow_http_loopback: bool = False,
) -> tuple[int, dict[str, Any]]:
    parsed = urlparse(endpoint)
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme != "https" and not (
        allow_http_loopback and parsed.scheme == "http" and loopback
    ):
        raise ValueError("federation endpoint must use HTTPS")
    if not token.strip():
        raise ValueError("federation bearer token is empty")
    data = path.read_bytes()
    envelope = json.loads(data.decode("utf-8"))
    resolved_provider = provider_id or (
        envelope.get("provider_id") if isinstance(envelope, dict) else None
    )
    if not institution_id.strip() or not resolved_provider:
        raise ValueError("federation institution and provider ids are required")
    request = Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "eii-observatory/0.1",
            "x-eii-institution-id": institution_id,
            "x-eii-provider-id": str(resolved_provider),
        },
    )
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise ValueError("federation response exceeds size limit")
            decoded = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(decoded, dict):
                raise ValueError("federation response must be a JSON object")
            return response.status, decoded
    except (HTTPError, URLError) as error:
        if isinstance(error, HTTPError):
            error.close()
        raise ValueError(f"federation submission failed: {error}") from error
