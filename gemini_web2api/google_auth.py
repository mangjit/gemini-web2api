"""Google Sign-In for the playground. Never stores Gmail passwords."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import CONFIG

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
SESSION_COOKIE = "g2a_google"
SESSION_TTL = 30 * 24 * 3600
_oauth_states = {}


def client_id() -> str:
    return (os.environ.get("GOOGLE_CLIENT_ID") or CONFIG.get("google_client_id") or "").strip()


def client_secret() -> str:
    return (os.environ.get("GOOGLE_CLIENT_SECRET") or CONFIG.get("google_client_secret") or "").strip()


def session_secret() -> bytes:
    return (
        os.environ.get("SESSION_SECRET")
        or client_secret()
        or "gemini-web2api-google-session"
    ).encode()


def public_origin(handler) -> str:
    proto = handler.headers.get("X-Forwarded-Proto") or ""
    host = handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "localhost"
    if not proto:
        proto = "https" if "onrender.com" in host or "e2b.app" in host else "http"
    return f"{proto}://{host.split(',')[0].strip()}"


def redirect_uri(handler) -> str:
    return public_origin(handler) + "/auth/google/callback"


def _pkce() -> tuple:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def service_login_url(handler=None) -> str:
    """Add-account Google login (email then password).

    Must not use continue=this-app (Google HTTP 400), continue=www.google.com
    (skips login and opens Search), or gemini.google.com (leaves the user there).
    """
    del handler
    return "https://accounts.google.com/v3/signin/identifier?" + urllib.parse.urlencode(
        {
            "hl": "en",
            "flowName": "GlifWebSignIn",
            "flowEntry": "AddSession",
            "continue": "https://accounts.google.com/",
        }
    )


def google_login_redirect(handler) -> str:
    """Popup target after Sign in. OAuth when configured, otherwise Google login."""
    return authorization_url(handler) or service_login_url(handler)


def authorization_url(handler):
    """Google account picker for this app. Never opens gemini.google.com."""
    cid = client_id()
    if not cid:
        return None
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    now = time.time()
    for key, meta in list(_oauth_states.items()):
        if now - meta.get("created", 0) > 600:
            _oauth_states.pop(key, None)
    _oauth_states[state] = {"verifier": verifier, "created": now}
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(handler),
        "response_type": "code",
        "scope": "openid email profile",
        "prompt": "select_account consent",
        "access_type": "online",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return GOOGLE_AUTH + "?" + urllib.parse.urlencode(params)


def _http_json(url: str, data: dict = None, headers: dict = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Google auth failed ({exc.code}): {detail}") from exc


def profile_from_access_token(token: str) -> dict:
    data = _http_json(GOOGLE_USERINFO, headers={"Authorization": "Bearer " + token})
    if not data.get("email") and not data.get("sub"):
        raise RuntimeError("Google did not return an account")
    return data


def profile_from_id_token(token: str) -> dict:
    data = _http_json(GOOGLE_TOKENINFO + "?" + urllib.parse.urlencode({"id_token": token}))
    aud = data.get("aud") or ""
    cid = client_id()
    if cid and aud and aud != cid:
        raise RuntimeError("Google token was issued for a different app")
    if not data.get("email") and not data.get("sub"):
        raise RuntimeError("Google did not return an account")
    return data


def profile_from_callback(handler, query: dict) -> dict:
    if query.get("error"):
        raise RuntimeError(query.get("error_description") or query.get("error") or "Google sign-in cancelled")
    state = (query.get("state") or [""])[0] if isinstance(query.get("state"), list) else (query.get("state") or "")
    code = (query.get("code") or [""])[0] if isinstance(query.get("code"), list) else (query.get("code") or "")
    meta = _oauth_states.pop(state, None)
    if not code:
        raise RuntimeError("Google did not return an authorization code")
    if not meta:
        raise RuntimeError("Sign-in expired. Try Sign in with Google again.")
    payload = {
        "code": code,
        "client_id": client_id(),
        "redirect_uri": redirect_uri(handler),
        "grant_type": "authorization_code",
        "code_verifier": meta["verifier"],
    }
    secret = client_secret()
    if secret:
        payload["client_secret"] = secret
    tokens = _http_json(GOOGLE_TOKEN, data=payload)
    if tokens.get("id_token"):
        return profile_from_id_token(tokens["id_token"])
    if tokens.get("access_token"):
        return profile_from_access_token(tokens["access_token"])
    raise RuntimeError("Google did not return tokens")


def profile_from_browser_payload(body: dict) -> dict:
    if body.get("credential"):
        return profile_from_id_token(str(body["credential"]))
    if body.get("access_token"):
        return profile_from_access_token(str(body["access_token"]))
    raise RuntimeError("Missing Google credential")


def encode_session(profile: dict) -> str:
    payload = json.dumps(
        {
            "email": profile.get("email") or "",
            "sub": profile.get("sub") or "",
            "name": profile.get("name") or "",
            "exp": int(time.time()) + SESSION_TTL,
        },
        separators=(",", ":"),
    )
    raw = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    sig = hmac.new(session_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + sig


def decode_session(value: str):
    if not value or "." not in value:
        return None
    raw, sig = value.rsplit(".", 1)
    expect = hmac.new(session_secret(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    pad = "=" * (-len(raw) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + pad))
    except (json.JSONDecodeError, ValueError):
        return None
    if int(data.get("exp") or 0) < time.time():
        return None
    return data


def read_session_cookie(cookie_header: str):
    for part in (cookie_header or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip() == SESSION_COOKIE:
            return decode_session(urllib.parse.unquote(value.strip()))
    return None


def session_set_cookie(value: str, secure: bool) -> str:
    cookie = (
        f"{SESSION_COOKIE}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}"
    )
    if secure:
        cookie += "; Secure"
    return cookie


def session_clear_cookie(secure: bool) -> str:
    cookie = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
    if secure:
        cookie += "; Secure"
    return cookie


def popup_done_html(profile: dict) -> str:
    payload = json.dumps({
        "source": "gemini-web2api-auth",
        "type": "signed-in",
        "email": profile.get("email") or "",
        "name": profile.get("name") or "",
    })
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Back to gemini-web2api</title></head>"
        "<body style='font-family:sans-serif;padding:24px;background:#101624;color:#eef3ff'>"
        "<p>You can close this window.</p>"
        "<button type='button' onclick='window.close()' style='padding:10px 16px;border-radius:10px;border:0;cursor:pointer'>Close</button>"
        "<script>try{if(window.opener)window.opener.postMessage("
        + payload
        + ",window.location.origin);}catch(e){}"
        "setTimeout(function(){window.close();},200);</script>"
        "</body></html>"
    )
