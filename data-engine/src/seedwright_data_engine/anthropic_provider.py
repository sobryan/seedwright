"""The Anthropic Messages API as a second real authoring provider (NFR-AGNOSTIC).

Proves the provider abstraction is real: the same evaluator-optimizer loop, the same prompt, and
the same best-effort genspec extraction that back the Copilot CLI provider work unchanged behind
a different transport (an HTTP call to Anthropic). Only *who writes the genspec* changes —
execution stays deterministic and model-free (the §3 keystone).

The HTTP call sits behind an injectable ``runner`` so the loop is fully testable offline (no
network, no key). Uses stdlib ``urllib`` — no provider SDK dependency. Privacy is the user's
provider choice (NFR-PRIV): selecting this provider sends example-derived schema/rules to
Anthropic, exactly as the spec says the authoring model receives them.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from seedwright_authoring.capability import Capabilities
from seedwright_authoring.provider import ProposeRequest, ProposeResponse

from .copilot_provider import build_prompt, extract_genspec

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TIMEOUT_SECONDS = 180


def build_request(prompt: str, *, model: str, api_key: str,
                  max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    """Assemble the Messages API request (url + headers + JSON body). Pure — no I/O."""
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    return {
        "url": ANTHROPIC_URL,
        "headers": {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        "body": body,
    }


def parse_reply(api_json: str) -> str:
    """Extract the assistant text from a Messages API response; ``""`` on any unexpected shape.

    An empty string flows into ``extract_genspec`` as ``{}`` -> a PARSE_ERROR the loop refines on,
    so a blocked/malformed/truncated reply never crashes authoring.
    """
    try:
        payload = json.loads(api_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    blocks = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(blocks, list):
        return ""
    return "".join(
        b["text"] for b in blocks
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    )


def _call_anthropic(prompt: str, *, model: str, api_key: str, timeout: int) -> str:
    """POST the prompt to the Messages API and return the RAW response JSON (real network call).

    Returning the raw body keeps one runner contract: every runner (real or injected in tests)
    yields the Messages API response JSON, and ``propose`` does parse_reply -> extract_genspec.
    """
    req_spec = build_request(prompt, model=model, api_key=api_key)
    request = urllib.request.Request(  # noqa: S310 — fixed https endpoint, not user-controlled
        req_spec["url"],
        data=req_spec["body"].encode("utf-8"),
        headers=req_spec["headers"],
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return str(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Anthropic API error {exc.code}: {detail}") from exc


class AnthropicProvider:
    """Authoring provider backed by the Anthropic Messages API."""

    provider_id = "anthropic"

    def __init__(
        self,
        *,
        foreign_keys: dict[str, list[dict[str, Any]]] | None = None,
        volumes: dict[str, int] | None = None,
        seed: int = 42,
        runner: Callable[[str], str] | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._foreign_keys = foreign_keys
        self._volumes = volumes
        self._seed = seed
        self._model = model or os.environ.get("SEEDWRIGHT_ANTHROPIC_MODEL", DEFAULT_MODEL)
        # runner returns the raw Messages API response JSON as text; the default hits the network.
        if runner is not None:
            self._runner = runner
        else:
            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — the anthropic provider needs an API key "
                    "(FR-H.7: authoring failure is surfaced, not silently degraded)")
            self._runner = lambda prompt: _call_anthropic(
                prompt, model=self._model, api_key=key, timeout=timeout)

    def capabilities(self) -> Capabilities:
        return Capabilities(structured_json_output=True)

    def propose(self, request: ProposeRequest) -> ProposeResponse:
        prompt = build_prompt(request, foreign_keys=self._foreign_keys,
                              volumes=self._volumes, seed=self._seed)
        raw_response = self._runner(prompt)          # Messages API response JSON
        assistant_text = parse_reply(raw_response)   # -> the assistant's text (or "" if blocked)
        return ProposeResponse(genspec=extract_genspec(assistant_text))
