"""
Everything that talks to Gemini: text-to-speech generation, plus converting
Gemini's raw PCM audio output into a proper WAV file the browser can play.
"""
import base64
import re

import httpx

from config import GEMINI_API_KEY, GEMINI_TTS_MODEL, GEMINI_TTS_VOICE


async def synthesize_speech(text: str) -> dict:
    """Sends reply text to Gemini TTS. Returns:
    {'ok': True, 'audio': bytes} (a ready-to-play WAV file) on success, or
    {'ok': False, 'status': int, 'error': str} on failure.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == '':
        return {'ok': False, 'status': 500, 'error': 'GEMINI_API_KEY is not set — add your real key to the .env file.'}

    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TTS_MODEL}:generateContent',
            headers={'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'},
            json={
                'contents': [{'parts': [{'text': text}]}],
                'generationConfig': {
                    'responseModalities': ['AUDIO'],
                    'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': GEMINI_TTS_VOICE}}},
                },
            },
        )

    if res.status_code >= 400:
        return {'ok': False, 'status': res.status_code, 'error': _safe_err_text(res)}

    data = res.json()
    candidates = data.get('candidates', [])
    part = candidates[0].get('content', {}).get('parts', [{}])[0] if candidates else {}
    inline_data = part.get('inlineData', {})
    audio_b64 = inline_data.get('data')

    if not audio_b64:
        return {'ok': False, 'status': 502, 'error': 'Gemini TTS returned no audio content'}

    # Gemini TTS returns raw 16-bit PCM (mono, 24kHz by default) — mimeType looks like
    # "audio/L16;codec=pcm;rate=24000". Browsers can't play raw PCM directly via <audio>,
    # so wrap it in a standard WAV header before sending it down.
    mime_type = inline_data.get('mimeType', '')
    rate_match = re.search(r'rate=(\d+)', mime_type)
    sample_rate = int(rate_match.group(1)) if rate_match else 24000
    pcm_bytes = base64.b64decode(audio_b64)
    wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate=sample_rate, channels=1, bit_depth=16)

    return {'ok': True, 'audio': wav_bytes}


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int, bit_depth: int) -> bytes:
    """Prepends a standard 44-byte WAV header to raw PCM data."""
    import struct
    byte_rate = sample_rate * channels * bit_depth // 8
    block_align = channels * bit_depth // 8
    header = b'RIFF'
    header += struct.pack('<I', 36 + len(pcm_bytes))
    header += b'WAVEfmt '
    header += struct.pack('<IHHIIHH', 16, 1, channels, sample_rate, byte_rate, block_align, bit_depth)
    header += b'data'
    header += struct.pack('<I', len(pcm_bytes))
    return header + pcm_bytes


def _safe_err_text(resp: httpx.Response) -> str:
    try:
        err_body = resp.json()
        return err_body.get('error', {}).get('message', resp.reason_phrase)
    except Exception:
        return resp.reason_phrase