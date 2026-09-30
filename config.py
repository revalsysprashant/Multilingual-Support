"""
Configuration — every setting the app needs lives here, loaded from environment
variables (via a .env file) rather than hardcoded. This is the ONLY file that
touches os.environ; every other module imports its settings from here.

Copy .env.example to .env and fill in your real keys before running the app.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present


def _get_required(name: str, hint: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        print(f"WARNING: {name} is not set in your .env file. {hint}")
    return value


# ---------------------------------------------------------------------------
# Secrets — from .env, never hardcoded here.
# ---------------------------------------------------------------------------
GROQ_API_KEY = _get_required('GROQ_API_KEY', 'Speech-to-text and chat replies will fail until this is set.')
GEMINI_API_KEY = _get_required('GEMINI_API_KEY', 'Voice replies will fail until this is set.')
SESSION_SECRET = os.getenv('SESSION_SECRET', 'change-this-to-a-long-random-string-before-deploying')
PORT = int(os.getenv('PORT', '3000'))

# ---------------------------------------------------------------------------
# JWT (login tokens) — issued when someone logs in/signs up, verified on every
# protected request. JWT_SECRET signs the token; if unset, falls back to
# SESSION_SECRET so you don't need two separate secrets to manage.
# JWT_EXPIRE_MINUTES is a safety net independent of the cookie itself — even if
# the browser somehow kept the cookie around, the token inside it still expires.
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv('JWT_SECRET', SESSION_SECRET)
JWT_ALGORITHM = 'HS256'
JWT_EXPIRE_MINUTES = int(os.getenv('JWT_EXPIRE_MINUTES', str(7 * 24 * 60)))  # 7 days

# ---------------------------------------------------------------------------
# Concurrency / rate-limit handling — matters once more than one or two people
# use the app at the same time, since everyone shares the same Groq/Gemini key.
# GROQ_MAX_CONCURRENT / GEMINI_MAX_CONCURRENT cap how many requests to each API
# this server sends out simultaneously; extras wait their turn instead of all
# firing at once. API_MAX_RETRIES controls how many times a request auto-retries
# if the API responds with 429 (Too Many Requests) despite that.
# ---------------------------------------------------------------------------
GROQ_MAX_CONCURRENT = int(os.getenv('GROQ_MAX_CONCURRENT', '3'))
GEMINI_MAX_CONCURRENT = int(os.getenv('GEMINI_MAX_CONCURRENT', '3'))
API_MAX_RETRIES = int(os.getenv('API_MAX_RETRIES', '3'))

# ---------------------------------------------------------------------------
# Groq models (edit here if Groq renames/deprecates one)
# ---------------------------------------------------------------------------
# whisper-large-v3 (not the -turbo variant) trades a bit of speed for noticeably better accuracy,
# and supports auto-detecting/transcribing 90+ languages, not just English.
STT_MODEL = 'whisper-large-v3'
# llama-3.3-70b-versatile was decommissioned by Groq on Aug 16, 2026.
# openai/gpt-oss-120b is Groq's recommended replacement (qwen/qwen3.6-27b is the smaller alternative) —
# it also happens to advertise strong 81+ language performance, which fits the multilingual feature well.
LLM_MODEL = 'openai/gpt-oss-120b'

# ---------------------------------------------------------------------------
# Gemini TTS (text-to-speech) — Groq's Orpheus only ever supported English, so
# voice output runs on Gemini instead. Gemini's TTS auto-detects language from
# the text itself, so one voice name covers every supported language.
# ---------------------------------------------------------------------------
GEMINI_TTS_MODEL = 'gemini-2.5-flash-preview-tts'  # stays on the free tier (Flash-class model)
GEMINI_TTS_VOICE = 'Kore'

# ---------------------------------------------------------------------------
# Languages the chatbot will actually converse in. Whisper can transcribe far more
# than this list, but the LLM is instructed to only *respond* in one of these —
# anything else gets the "not supported yet" message. Edit this list to change
# what's supported; the LLM reads this same list to decide what counts as supported.
# ---------------------------------------------------------------------------
SUPPORTED_LANGUAGES = [
    'English', 'Hindi', 'Telugu', 'Tamil', 'Kannada', 'Malayalam',
    'Marathi', 'Bengali', 'Gujarati', 'Punjabi', 'Urdu', 'Spanish', 'French'
]
TTS_SUPPORTED_LANGUAGES = SUPPORTED_LANGUAGES


def build_system_prompt() -> str:
    return (
        f"You are a multilingual voice support assistant. You can converse in these languages: {', '.join(SUPPORTED_LANGUAGES)}.\n\n"
        "For every user message, follow these steps:\n"
        "1. Detect the language of the user's most recent message. Language can change between turns — always match the language of the CURRENT message, not earlier ones in the conversation.\n"
        "2. If that language is in the supported list above: understand the intent using the full conversation history (even turns that were in a different language), then write your reply entirely in that same language, matching its natural phrasing and script — not a literal word-for-word translation. Keep it short and natural to speak aloud (1-3 sentences), avoid markdown/lists/symbols, and preserve exact values (names, prices, dates, numbers, product names) unchanged and untranslated.\n"
        "3. If that language is NOT in the supported list: do not attempt to answer the underlying question. Instead, politely say in English that this language isn't supported yet, and list the supported languages from above.\n"
        "4. If the request is genuinely ambiguous, ask a brief clarifying question in the same language instead of guessing.\n\n"
        "Respond with ONLY a raw JSON object — no markdown code fences, no text outside the JSON — in exactly this shape:\n"
        '{"language_name": "<the language the user just used, e.g. Telugu>", "supported": true or false, "reply": "<your reply text>"}'
    )


# Fed to Whisper as an "initial prompt" — Whisper tends to continue in whichever script/language
# the prompt is written in, so giving it one real sample sentence per supported language helps it
# commit to the correct language early instead of drifting into garbled or wrong-script output.
# This especially helps lower-resource languages (Telugu, Tamil) where Whisper has less training data.
STT_PROMPT_HINT = (
    'Hello, how can I help you today? नमस्ते, मैं आपकी कैसे मदद कर सकता हूँ? '
    'నమస్తే, నేను మీకు ఎలా సహాయం చేయగలను? வணக்கம், நான் உங்களுக்கு எப்படி உதவ முடியும்? '
    'ನಮಸ್ಕಾರ, ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು? നമസ്കാരം, ഞാൻ നിങ്ങളെ എങ്ങനെ സഹായിക്കും?'
)