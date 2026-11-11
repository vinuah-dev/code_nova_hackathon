"""Claude integration: grounded brand-compliance review.

The model only sees (1) the content and (2) the Brand Brain chunks retrieved for
it. It must cite those chunk ids. We validate every citation server-side; a
finding without a valid citation is kept but labelled "ungrounded" and its
confidence is reduced, so it can never masquerade as policy.
"""
import base64
import io
import json

from PIL import Image

from . import config

SYSTEM = """You are Inkloom, a brand-governance reviewer. You check marketing content against an organisation's
approved brand knowledge before it is published.

Rules:
- Judge ONLY against the SOURCES provided. Every finding must cite one or more source ids from SOURCES in source_ids.
  If you notice a problem that no source covers, you may still report it but leave source_ids empty.
- "quote" must be copied exactly, character for character, from the target text (body, alt_text or pdf), and be as short
  as possible while still identifying the problem (a word or phrase, not the whole paragraph). For image findings use "".
- Focus on what a deterministic checker cannot catch: tone and voice drift, messaging that conflicts with positioning,
  implied or paraphrased claims without evidence, misleading framing, logo and visual misuse visible in images,
  inaccessible visual design. Do not repeat issues already listed under ALREADY FOUND.
- "replacement" must be a drop-in substitute for "quote" that keeps the creator's purpose and meaning, uses approved
  wording where possible, and fits grammatically. Use "" if a human must decide.
- Be calibrated: confidence 0.9+ only when a source clearly rules on it. Do not invent facts or numbers.
- Report at most 12 findings. If the content is compliant, return an empty list."""

FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["tone", "terminology", "claims", "facts", "visual", "accessibility"]},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "title": {"type": "string"},
                    "target": {"type": "string", "enum": ["body", "alt_text", "pdf", "image"]},
                    "quote": {"type": "string"},
                    "explanation": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "replacement": {"type": "string"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["category", "severity", "title", "target", "quote", "explanation", "source_ids",
                             "replacement", "rationale", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "findings"],
    "additionalProperties": False,
}


class AIUnavailable(Exception):
    pass


def _client():
    if not config.ai_configured():
        raise AIUnavailable("No ANTHROPIC_API_KEY configured")
    import anthropic
    return anthropic.Anthropic(timeout=150.0, max_retries=1)


def _image_block(path: str) -> dict:
    img = Image.open(path).convert("RGB")
    img.thumbnail((1400, 1400))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def _call(system: str, content: list, schema: dict, max_tokens: int = 16000) -> dict:
    if not config.ai_configured():
        raise AIUnavailable("No AI provider configured")
    if config.provider() != "anthropic":
        return _call_openai_compatible(system, content, schema, max_tokens)
    return _call_anthropic(system, content, schema, max_tokens)


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise AIUnavailable("AI returned no JSON")
    try:
        return json.loads(t[start:end + 1])
    except ValueError as e:
        raise AIUnavailable("AI returned invalid JSON") from e


def _call_openai_compatible(system: str, content: list, schema: dict, max_tokens: int) -> dict:
    """Gemini / Groq / OpenRouter / Ollama via the OpenAI-compatible /chat/completions API (stdlib only)."""
    import urllib.error
    import urllib.request
    parts = []
    for blk in content:
        if blk["type"] == "text":
            parts.append({"type": "text", "text": blk["text"]})
        elif blk["type"] == "image":
            if config.send_images():
                src = blk["source"]
                parts.append({"type": "image_url", "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
            else:
                parts.append({"type": "text", "text": "(image omitted: this model is configured without image input)"})
    sys_prompt = (system + "\n\nRespond with ONE JSON object only, no prose, matching this JSON Schema:\n"
                  + json.dumps(schema))
    body = {"model": config.model(), "max_tokens": max_tokens, "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": parts}]}
    req = urllib.request.Request(config.base_url() + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key()}"})
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code in (401, 403):
            raise AIUnavailable("API key rejected") from e
        if e.code == 429:
            raise AIUnavailable("Rate limited by the AI service (free-tier limit?)") from e
        raise AIUnavailable(f"AI service error {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AIUnavailable("Could not reach the AI service") from e
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIUnavailable("Unexpected AI response format") from e
    if isinstance(text, list):  # some servers return content parts
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    if choice.get("finish_reason") == "length":
        raise AIUnavailable("AI response was cut off")
    return _extract_json(text)


def _call_anthropic(system: str, content: list, schema: dict, max_tokens: int) -> dict:
    import anthropic
    client = _client()
    try:
        resp = client.beta.messages.create(
            model=config.model(),
            max_tokens=max_tokens,
            system=system,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": config.effort(), "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("API key rejected") from e
    except anthropic.RateLimitError as e:
        raise AIUnavailable("Rate limited by the AI service") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("Could not reach the AI service") from e
    except anthropic.APIStatusError as e:
        raise AIUnavailable(f"AI service error {e.status_code}: {getattr(e, 'message', '')}"[:300]) from e
    if resp.stop_reason == "refusal":
        raise AIUnavailable("The model declined this request")
    if resp.stop_reason == "max_tokens":
        raise AIUnavailable("AI response was cut off")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise AIUnavailable("Empty AI response")
    try:
        return json.loads(text)
    except ValueError as e:
        raise AIUnavailable("AI returned invalid JSON") from e


def review(body: str, alt_text: str, pdf_text: str, images: list[dict], official_logos: list[dict],
           sources: list[dict], rule_findings: list[dict]) -> dict:
    src = "\n".join(f"[{s['id']}] ({s['category']}) {s['title']}: {s['text']}" for s in sources)
    already = "\n".join(f"- {f['category']}: {f['title']} — \"{f.get('quote', '')}\"" for f in rule_findings) or "- none"
    content: list = [{"type": "text", "text": f"SOURCES (approved brand knowledge):\n{src}\n\nALREADY FOUND by the rule engine:\n{already}"}]
    content.append({"type": "text", "text": f"CONTENT TO REVIEW\n\n<body>\n{body or ''}\n</body>\n\n<alt_text>\n{alt_text or ''}\n</alt_text>"
                                             + (f"\n\n<pdf>\n{pdf_text[:20000]}\n</pdf>" if pdf_text else "")})
    for im in images:
        content.append({"type": "text", "text": f"IMAGE in the content ({im['kind']}): {im['name']}"})
        content.append(_image_block(im["path"]))
    for lg in official_logos[:2]:
        content.append({"type": "text", "text": f"REFERENCE — official logo from the Brand Brain: {lg['name']} (source id G-VIS-02)"})
        content.append(_image_block(lg["path"]))
    content.append({"type": "text", "text": "Review the content now. Return JSON only."})
    return _call(SYSTEM, content, FINDING_SCHEMA)


GUIDELINE_SCHEMA = {
    "type": "object",
    "properties": {"proposed_text": {"type": "string"}, "why": {"type": "string"}},
    "required": ["proposed_text", "why"], "additionalProperties": False,
}


def propose_guideline(guideline: dict, pattern: str, examples: list[str]) -> dict:
    content = [{"type": "text", "text": (
        f"Current guideline [{guideline['id']}] {guideline['title']}:\n{guideline['body']}\n\n"
        f"Repeated mistake seen across submissions: {pattern}\nExamples:\n" + "\n".join(f"- {e}" for e in examples[:8]) +
        "\n\nRewrite the guideline so creators would not make this mistake: keep everything that is already there, add the "
        "missing clarity (explicit do/don't, an example). Keep it under 120 words. Explain in one sentence why.")}]
    return _call("You improve brand guidelines so they are unambiguous for content creators.", content, GUIDELINE_SCHEMA, 4000)
