"""OpenAI-compatible model transport usable with hosted APIs or local vLLM."""

from __future__ import annotations

import json
import math
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .domain import ModelRun, content_hash

Transport = Callable[[str, bytes, Mapping[str, str], float], Mapping[str, Any]]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise HTTPError(req.full_url, code, "model endpoint redirect refused", headers, fp)


def _http_transport(
    url: str, body: bytes, headers: Mapping[str, str], timeout: float
) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    request = Request(url, body, dict(headers), method="POST")
    # The URL is constructed only after explicit HTTP(S) validation in the client constructor.
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
    with opener.open(request, timeout=max(0.001, deadline - time.monotonic())) as response:
        parts: list[bytes] = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("model response deadline exceeded")
            raw = getattr(getattr(response, "fp", None), "raw", None)
            socket = getattr(raw, "_sock", None)
            if socket is not None:
                socket.settimeout(remaining)
            reader = getattr(response, "read1", response.read)
            part = reader(min(65_536, 4_194_305 - size))
            if not part:
                break
            parts.append(part)
            size += len(part)
            if size > 4_194_304:
                raise ValueError("model response exceeds 4 MiB limit")
        payload = b"".join(parts)
        return cast(Mapping[str, Any], json.loads(payload))


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    model_run: ModelRun


def _validate_chat_request(
    messages: list[Mapping[str, str]],
    prompt_version: str,
    temperature: float,
    timeout_seconds: float | None,
) -> None:
    if not prompt_version.strip():
        raise ValueError("prompt version must be non-empty")
    if not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("temperature must be finite and between zero and two")
    if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError("timeout override must be finite and positive")
    if not messages or len(messages) > 100:
        raise ValueError("model request must contain between 1 and 100 messages")
    allowed_roles = {"system", "user", "assistant", "tool"}
    if any(
        message.get("role") not in allowed_roles
        or not isinstance(message.get("content"), str)
        or not message["content"]
        for message in messages
    ):
        raise ValueError("model messages require a supported role and non-empty text content")


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        provider: str = "openai-compatible",
        api_key: str | None = None,
        timeout: float = 60,
        transport: Transport | None = None,
        retries: int = 2,
        model_revision: str | None = None,
    ):
        endpoint = urlparse(base_url)
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
            raise ValueError("model base URL must be an explicit HTTP(S) endpoint")
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("model base URL must not contain credentials, query, or fragment")
        if endpoint.scheme == "http" and endpoint.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise ValueError("non-loopback model endpoints must use HTTPS")
        if not model.strip() or timeout <= 0 or retries < 0 or retries > 10:
            raise ValueError("model, positive timeout, and retries between 0 and 10 are required")
        if model_revision is not None and not model_revision.strip():
            raise ValueError("model revision must be non-empty when supplied")
        self.base_url = base_url.rstrip("/")
        self.model, self.provider, self.api_key, self.timeout = model, provider, api_key, timeout
        self.transport = transport or _http_transport
        self.retries = retries
        self.model_revision = model_revision

    def chat(
        self,
        messages: list[Mapping[str, str]],
        *,
        prompt_version: str,
        temperature: float = 0,
        response_format: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> ChatResult:
        _validate_chat_request(messages, prompt_version, temperature, timeout_seconds)
        effective_timeout = min(self.timeout, timeout_seconds) if timeout_seconds else self.timeout
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = time.monotonic()
        deadline = started + effective_timeout
        attempt = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("model request deadline exceeded")
            try:
                result = self.transport(
                    f"{self.base_url}/chat/completions", body, headers, remaining
                )
                break
            except HTTPError as error:
                retry = error.code in {408, 429, 500, 502, 503, 504} and attempt < self.retries
                error.close()
                if not retry:
                    raise
                time.sleep(min(0.25 * (2**attempt), 2.0, max(0, deadline - time.monotonic())))
                attempt += 1
            except (OSError, TimeoutError):
                if attempt >= self.retries:
                    raise
                time.sleep(min(0.25 * (2**attempt), 2.0, max(0, deadline - time.monotonic())))
                attempt += 1
        latency = round((time.monotonic() - started) * 1000)
        try:
            text = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("model response lacks choices[0].message.content") from error
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 4_194_304:
            raise ValueError("model response content must be non-empty text no larger than 4 MiB")
        usage = result.get("usage", {})
        if not isinstance(usage, Mapping) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in usage.values()
        ):
            raise ValueError("model response usage must be an object")
        cost = result.get("cost")
        if cost is not None and (
            not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0
        ):
            raise ValueError("model response cost must be a non-negative number")
        response_model = result.get("model")
        system_fingerprint = result.get("system_fingerprint")
        request_id = result.get("id")
        if any(
            value is not None and (not isinstance(value, str) or not value.strip())
            for value in (response_model, system_fingerprint, request_id)
        ):
            raise ValueError("model identity fields must be non-empty strings when supplied")
        effective_revision = self.model_revision or (
            f"{response_model}@{system_fingerprint}"
            if response_model and system_fingerprint
            else None
        )
        configuration = {
            "endpoint_hash": content_hash(self.base_url),
            "temperature": temperature,
            "configured_timeout_seconds": self.timeout,
            "effective_timeout_seconds": effective_timeout,
            "retries": self.retries,
            "attempt_count": attempt + 1,
            "model_revision": self.model_revision,
            "response_model": response_model,
            "system_fingerprint": system_fingerprint,
            "effective_model_revision": effective_revision,
            "reproducible_model_identity": effective_revision is not None,
            "request_id_hash": content_hash(request_id) if request_id else None,
            "usage": dict(usage),
            "response_format": response_format,
            "response_envelope_hash": content_hash(result),
            # Retain the exact non-secret request needed to recompute input_hash.
            "request_payload": payload,
        }
        run = ModelRun(
            self.provider,
            self.model,
            prompt_version,
            configuration,
            content_hash(payload),
            content_hash(text),
            latency_ms=latency,
            cost=cost,
        )
        return ChatResult(text, run)
