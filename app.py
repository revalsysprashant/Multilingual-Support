"""
Voice Support — FastAPI app.

This file wires everything together but keeps almost no logic of its own —
each route just calls into one of the focused modules:
  config.py         — all settings, loaded from .env
  auth.py           — accounts, passwords
  jwt_auth.py        — login tokens (JWT) issued at login, verified per request
  history_store.py  — per-user saved conversations
  groq_client.py     — speech-to-text + the chat LLM
  gemini_client.py    — text-to-speech
"""
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import Cookie, Depends, FastAPI, File, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import auth
import gemini_client
import groq_client
import history_store
import jwt_auth
from config import PORT, SUPPORTED_LANGUAGES, TTS_SUPPORTED_LANGUAGES

BASE_DIR = Path(__file__).parent
VIEWS_DIR = BASE_DIR / 'views'
PUBLIC_DIR = BASE_DIR / 'public'

app = FastAPI()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class SignupIn(BaseModel):
    username: str = ''
    password: str = ''


class LoginIn(BaseModel):
    username: str = ''
    password: str = ''


class MessageIn(BaseModel):
    text: str = ''


class SpeakIn(BaseModel):
    text: str = ''
    language: str | None = None  # currently unused — Gemini TTS auto-detects language from the text


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.post('/api/signup')
async def signup(body: SignupIn, response: Response):
    username = body.username.strip()
    password = body.password

    if not auth.is_valid_username(username):
        return JSONResponse(status_code=400, content={'error': 'Username must be 3-32 characters: letters, numbers, underscore only.'})
    if not auth.is_valid_password(password):
        return JSONResponse(status_code=400, content={'error': 'Password must be at least 6 characters.'})

    users = auth.load_users()
    key = auth.safe_username_key(username)
    if key in users:
        return JSONResponse(status_code=409, content={'error': 'That username is already taken.'})

    users[key] = {
        'username': username,
        'passwordHash': auth.hash_password(password),
        'createdAt': datetime.now(timezone.utc).isoformat(),
    }
    auth.save_users(users)

    _set_login_cookie(response, username)
    return {'ok': True, 'username': username}


@app.post('/api/login')
async def login(body: LoginIn, response: Response):
    username = body.username.strip()
    password = body.password

    users = auth.load_users()
    user = users.get(auth.safe_username_key(username))
    if not user or not auth.verify_password(password, user['passwordHash']):
        return JSONResponse(status_code=401, content={'error': 'Invalid username or password.'})

    _set_login_cookie(response, user['username'])
    return {'ok': True, 'username': user['username']}


@app.post('/api/logout')
async def logout(response: Response):
    response.delete_cookie(jwt_auth.COOKIE_NAME)
    return {'ok': True}


def _set_login_cookie(response: Response, username: str):
    """Issues a fresh JWT for this user and stores it in an httpOnly cookie —
    invisible to JavaScript, only the browser sends it automatically. No
    Max-Age/Expires set here (a "session cookie"), so it's cleared when the
    browser fully closes; the JWT's own 'exp' claim is a separate, independent
    safety net inside the token itself."""
    token = jwt_auth.create_access_token(username)
    response.set_cookie(
        key=jwt_auth.COOKIE_NAME,
        value=token,
        httponly=True,
        samesite='lax',
    )


@app.get('/api/me')
async def me(username: str = Depends(jwt_auth.require_auth)):
    return {'username': username}


@app.get('/api/languages')
async def languages(username: str = Depends(jwt_auth.require_auth)):
    return {'supported': SUPPORTED_LANGUAGES, 'ttsSupported': TTS_SUPPORTED_LANGUAGES}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.get('/')
async def serve_app(access_token: str | None = Cookie(default=None, alias=jwt_auth.COOKIE_NAME)):
    username = jwt_auth.decode_access_token(access_token) if access_token else None
    if not username:
        return RedirectResponse(url='/login.html')
    return FileResponse(VIEWS_DIR / 'app.html')


@app.get('/login.html')
async def serve_login():
    return FileResponse(PUBLIC_DIR / 'login.html')


# ---------------------------------------------------------------------------
# Protected API: voice/chat pipeline (all scoped to the logged-in user)
# ---------------------------------------------------------------------------
@app.get('/api/history')
async def get_history(username: str = Depends(jwt_auth.require_auth)):
    return {'messages': history_store.load_history(username)}


@app.post('/api/reset')
async def reset_history(username: str = Depends(jwt_auth.require_auth)):
    history_store.save_history(username, [])
    return {'ok': True}


@app.post('/api/transcribe')
async def transcribe(audio: UploadFile = File(...), username: str = Depends(jwt_auth.require_auth)):
    try:
        content = await audio.read()
        if not content:
            return JSONResponse(status_code=400, content={'error': 'No audio file received'})

        result = await groq_client.transcribe_audio(content, audio.content_type)
        if not result['ok']:
            print(f"Groq STT error: {result['status']} {result['error']}")
            return JSONResponse(status_code=result['status'], content={'error': result['error']})

        return {'text': result['text']}
    except Exception as e:
        print(e)
        return JSONResponse(status_code=500, content={'error': 'Transcription failed'})


@app.post('/api/message')
async def message(body: MessageIn, username: str = Depends(jwt_auth.require_auth)):
    try:
        user_text = body.text.strip()
        if not user_text:
            return JSONResponse(status_code=400, content={'error': 'Empty message'})

        history = history_store.load_history(username)
        history.append({'role': 'user', 'content': user_text})

        result = await groq_client.generate_reply(history)
        if not result['ok']:
            return JSONResponse(status_code=result['status'], content={'error': result['error']})

        parsed = result['parsed']
        reply_text = parsed.get('reply', '').strip() if isinstance(parsed, dict) and isinstance(parsed.get('reply'), str) else ''
        language_name = (
            parsed.get('language_name', '').strip()
            if isinstance(parsed, dict) and isinstance(parsed.get('language_name'), str) and parsed.get('language_name', '').strip()
            else 'English'
        )
        supported = isinstance(parsed, dict) and parsed.get('supported') is True

        if not reply_text:
            print(f"Model returned no usable reply. Raw output: {result['raw']}")
            reply_text = "Sorry, something went wrong generating that reply — could you try again?"
            language_name = 'English'
            supported = True

        history.append({'role': 'assistant', 'content': reply_text})
        history_store.save_history(username, history)

        return {
            'reply': reply_text,
            'language': language_name,
            'supported': supported,
            'ttsAvailable': language_name in TTS_SUPPORTED_LANGUAGES,
        }
    except Exception as e:
        print(e)
        return JSONResponse(status_code=500, content={'error': 'Response generation failed'})


@app.post('/api/speak')
async def speak(body: SpeakIn, username: str = Depends(jwt_auth.require_auth)):
    try:
        text = body.text.strip()
        if not text:
            return JSONResponse(status_code=400, content={'error': 'Empty text'})

        result = await gemini_client.synthesize_speech(text)
        if not result['ok']:
            print(f"Gemini TTS error: {result['status']} {result['error']}")
            return JSONResponse(status_code=result['status'], content={'error': result['error']})

        return Response(content=result['audio'], media_type='audio/wav')
    except Exception as e:
        print(e)
        return JSONResponse(status_code=500, content={'error': 'Speech generation failed'})


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=PORT)