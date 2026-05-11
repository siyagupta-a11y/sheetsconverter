import os
from typing import Optional
from urllib.parse import urlparse
from urllib.parse import quote
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

router = APIRouter()

# Google may return token scopes in a slightly different set/order
# (e.g. including userinfo scopes). Relax strict oauthlib scope validation.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_redirect_uri(request: Request) -> str:
    configured = os.getenv("GOOGLE_REDIRECT_URI")
    if configured:
        try:
            configured_host = (urlparse(configured).netloc or "").lower()
            request_host = (request.headers.get("host") or "").lower()
            # If a fixed redirect host is configured but does not match the current
            # request host (e.g. custom domain vs *.vercel.app), prefer dynamic host.
            if configured_host and request_host and configured_host == request_host:
                return configured
        except Exception:
            # Fall back to dynamic URI generation.
            pass
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/auth/callback"


def _make_flow(redirect_uri: str) -> Flow:
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)


def _creds_to_dict(creds: Credentials) -> dict:
    # SessionMiddleware stores data in signed cookies; keep payload minimal.
    # Prefer refresh-token based reconstruction to avoid oversized cookies.
    data = {
        "token_uri": creds.token_uri or "https://oauth2.googleapis.com/token",
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }
    if creds.refresh_token:
        data["refresh_token"] = creds.refresh_token
    else:
        # Fallback if refresh token is unavailable.
        data["token"] = creds.token
    return data


def get_credentials(request: Request) -> Optional[Credentials]:
    data = request.session.get("credentials")
    if not data:
        return None
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=data.get("scopes") or SCOPES,
    )
    # If we have a refresh token, always ensure a fresh access token.
    if creds.refresh_token and (not creds.token or creds.expired):
        try:
            creds.refresh(GoogleRequest())
            request.session["credentials"] = _creds_to_dict(creds)
        except Exception:
            request.session.pop("credentials", None)
            return None
    elif not creds.token:
        return None
    return creds


@router.get("/login")
async def login(request: Request):
    redirect_uri = _get_redirect_uri(request)
    flow = _make_flow(redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    request.session["oauth_state"] = state
    request.session["oauth_redirect_uri"] = redirect_uri
    if getattr(flow, "code_verifier", None):
        request.session["oauth_code_verifier"] = flow.code_verifier
    return RedirectResponse(auth_url)


@router.get("/callback")
async def callback(request: Request, code: str = None, state: str = None, error: str = None):
    if error:
        return RedirectResponse(f"/?auth_error={error}")

    stored_state = request.session.get("oauth_state")
    if not stored_state or stored_state != state:
        return RedirectResponse("/?auth_error=invalid_state")

    redirect_uri = request.session.get("oauth_redirect_uri", _get_redirect_uri(request))
    flow = _make_flow(redirect_uri)
    stored_verifier = request.session.get("oauth_code_verifier")
    if stored_verifier:
        flow.code_verifier = stored_verifier

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        detail = str(e)[:220] if e else "unknown"
        return RedirectResponse(f"/?auth_error=token_exchange_failed:{quote(detail)}")

    creds = flow.credentials
    request.session["credentials"] = _creds_to_dict(creds)
    request.session.pop("oauth_state", None)
    request.session.pop("oauth_redirect_uri", None)
    request.session.pop("oauth_code_verifier", None)

    return RedirectResponse("/")


@router.get("/status")
async def status(request: Request):
    creds = get_credentials(request)
    return JSONResponse({"authenticated": creds is not None})


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
