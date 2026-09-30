"""
Everything that talks to Groq: speech-to-text (Whisper) and the chat LLM
(GPT-OSS-120B), plus the safety-net parser for the LLM's structured
(language + reply) JSON output.
"""
import json
import re

import httpx

from config import GROQ_API_KEY, LLM_MODEL, STT_MODEL, STT_PROMPT_HINT, build_system_prompt


async def transcribe_audio(content: bytes, content_type: str | None) -> dict:
    """Sends recorded audio to Groq Whisper. Returns:
    {'ok': True, 'text': str} on success, or
    {'ok': False, 'status': int, 'error': str} on failure.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            'https://api.groq.com/openai/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            data={
                'model': STT_MODEL,
                'prompt': STT_PROMPT_HINT,
                'response_format': 'json',
                'temperature': '0',
            },
            files={'file': ('speech.webm', content, content_type or 'audio/webm')},
        )

    if res.status_code >= 400:
        return {'ok': False, 'status': res.status_code, 'error': _safe_err_text(res)}

    data = res.json()
    return {'ok': True, 'text': data.get('text', '')}


async def generate_reply(history: list[dict]) -> dict:
    """history: list of {'role': 'user'|'assistant', 'content': str}, most recent last.
    Returns {'ok': True, 'parsed': dict|None, 'raw': str} on success (parsed may be
    None if the model's JSON output couldn't be salvaged — caller handles the fallback),
    or {'ok': False, 'status': int, 'error': str} on a hard API failure.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'},
            json={
                'model': LLM_MODEL,
                'messages': [{'role': 'system', 'content': build_system_prompt()}, *history],
                'temperature': 0.4,
                'max_tokens': 400,
                # GPT-OSS models are reasoning models; 'low' keeps replies fast and conversational,
                # which matters for a voice assistant — we don't need deep chain-of-thought here.
                'reasoning_effort': 'low',
                'response_format': {'type': 'json_object'},
            },
        )

    if res.status_code >= 400:
        return {'ok': False, 'status': res.status_code, 'error': _safe_err_text(res)}

    data = res.json()
    raw = (data.get('choices', [{}])[0].get('message', {}).get('content') or '').strip()
    return {'ok': True, 'parsed': parse_model_json(raw), 'raw': raw}


def parse_model_json(raw: str):
    """Groq's JSON mode is usually clean, but models occasionally wrap output in ```json
    fences, add stray whitespace, or (GPT-OSS models specifically) leak internal control
    tokens like <|return|> or <|channel|> — strip all of that before parsing rather than
    failing outright. Returns a dict, or None if nothing usable could be salvaged."""
    text = raw.strip()
    text = re.sub(r'<\|[a-zA-Z_]+\|>', ' ', text).strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'```$', '', text).strip()
    # Grab the outermost {...} block in case any stray text survived the cleanup above.
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except Exception as e:
        print(f'Failed to parse model JSON output: {e}\nRaw: {raw}')
        return None


def _safe_err_text(resp: httpx.Response) -> str:
    try:
        j = resp.json()
        return j.get('error', {}).get('message') if isinstance(j.get('error'), dict) else json.dumps(j)
    except Exception:
        return resp.reason_phrase