from __future__ import annotations

import json
from typing import Any, Protocol

from .models import StoryIntelligenceContent, TokenUsage


class IntelligenceError(RuntimeError): pass
class MissingAPIKeyError(IntelligenceError): pass
class MalformedResponseError(IntelligenceError): pass


class ResponseClient(Protocol):
    def generate(self, *, model: str, system: str, user: str, max_output_tokens: int,
                 reasoning_effort: str, verbosity: str) -> tuple[StoryIntelligenceContent, str | None, TokenUsage]: ...


class OpenAIResponsesClient:
    """Thin SDK adapter; callers and UI remain independent of OpenAI."""
    def __init__(self, api_key: str | None):
        if not api_key: raise MissingAPIKeyError("OPENAI_API_KEY is not configured.")
        from openai import OpenAI
        self._client=OpenAI(api_key=api_key, timeout=90.0, max_retries=2)

    def generate(self, *, model: str, system: str, user: str, max_output_tokens: int,
                 reasoning_effort: str, verbosity: str):
        try:
            response=self._client.responses.parse(model=model,
                input=[{"role":"system","content":system},{"role":"user","content":user}],
                text_format=StoryIntelligenceContent, max_output_tokens=max_output_tokens,
                reasoning={"effort":reasoning_effort}, text={"verbosity":verbosity})
            parsed=response.output_parsed
            if parsed is None:
                parsed=StoryIntelligenceContent.model_validate(json.loads(response.output_text))
            usage=response.usage
            details=getattr(usage,"input_tokens_details",None); out_details=getattr(usage,"output_tokens_details",None)
            tokens=TokenUsage(input_tokens=getattr(usage,"input_tokens",None),
                cached_input_tokens=getattr(details,"cached_tokens",None), output_tokens=getattr(usage,"output_tokens",None),
                reasoning_tokens=getattr(out_details,"reasoning_tokens",None), total_tokens=getattr(usage,"total_tokens",None))
            return parsed, getattr(response,"id",None), tokens
        except IntelligenceError: raise
        except Exception as exc:
            raise IntelligenceError(f"OpenAI report generation failed: {type(exc).__name__}: {exc}") from exc
