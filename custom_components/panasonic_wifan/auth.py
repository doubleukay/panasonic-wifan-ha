import aiohttp
import base64
from datetime import datetime as dt, timedelta
import hashlib
import html
import logging
import os
import re
import secrets
import urllib.parse

from .types import AuthToken

_LOGGER = logging.getLogger(__name__)


AUTH_BASE = "https://authglb.digital.panasonic.com"
OAUTH_CLIENT_ID = "8k1QeEXDxt3qGgYOvDY7NmZLfl60YfNi"
AUTH0_CLIENT = "eyJuYW1lIjoiYXV0aDAuanMtdWxwIiwidmVyc2lvbiI6IjkuMjguMCJ9"
REDIRECT_URI = "panasonic-mycfan://authglb.digital.panasonic.com/android/com.panasonic.mycfan/callback"
REFRESH_TOKEN_GRACE_PERIOD = timedelta(minutes=5)


class PanasonicGLBAuthClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password

        self.auth_token: AuthToken | None = None
        self.access_token: str = ""
        self.session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(),
        )

    async def get_access_token(self) -> str:
        if self.auth_token:
            if self.auth_token.expiry - dt.now() < REFRESH_TOKEN_GRACE_PERIOD:
                await self.refresh_token()
            return self.auth_token.access_token

        self.auth_token = await self.login()
        return self.auth_token.access_token

    async def login(self) -> AuthToken:
        """
        Logs in to Panasonic via authglb and returns a dict with:
        - access_token
        - refresh_token
        """

        # STEP 0 – PKCE + state
        code_verifier, code_challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(20)

        # STEP 1 – authorize (no redirects)
        _LOGGER.debug("PanasonicGLBAuthClient.login() - step 1")
        r1 = await self.session.get(
            AUTH_BASE + "/authorize",
            params={
                "scope": "openid offline_access mycfan.control",
                "audience": f"https://digital.panasonic.com/{OAUTH_CLIENT_ID}/api/v1/",
                "protocol": "oauth2",
                "response_type": "code",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "auth0Client": AUTH0_CLIENT,
                "client_id": OAUTH_CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "state": state,
            },
            allow_redirects=False,
        )
        r1.raise_for_status()
        location = r1.headers.get("Location")
        if not location:
            raise RuntimeError("No Location header in /authorize response")

        # Panasonic/Auth0 may override the state in the redirect
        state = extract_state_from_location(location, state)

        # STEP 2 – follow redirect to get CSRF cookie
        _LOGGER.debug("PanasonicGLBAuthClient.login() - step 2")
        r2 = await self.session.get(
            urllib.parse.urljoin(AUTH_BASE, location),
            allow_redirects=False,
        )
        r2.raise_for_status()
        csrf = get_csrf_from_cookies(self.session)
        if not csrf:
            raise RuntimeError("No _csrf cookie found")

        # STEP 3 – username/password login
        login_payload = {
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "tenant": "pdpauthglb-a1",
            "response_type": "code",
            "scope": "openid offline_access mycfan.control",
            "audience": f"https://digital.panasonic.com/{OAUTH_CLIENT_ID}/api/v1/",
            "_csrf": csrf,
            "state": state,
            "_intstate": "deprecated",
            "username": self.email,
            "password": self.password,
            "lang": "en",
            "connection": "PanasonicID-Authentication",
        }

        _LOGGER.debug("PanasonicGLBAuthClient.login() - step 3")
        r3 = await self.session.post(
            AUTH_BASE + "/usernamepassword/login",
            json=login_payload,
            headers={
                "Auth0-Client": AUTH0_CLIENT,
            },
            allow_redirects=False,
        )
        r3.raise_for_status()
        html_text = await r3.text()

        # The HTML response contains hidden inputs (wa, wresult, wctx, etc.)
        form_data = extract_hidden_inputs(html_text)

        # STEP 4 – login callback (form POST)
        _LOGGER.debug("PanasonicGLBAuthClient.login() - step 4")
        r4 = await self.session.post(
            AUTH_BASE + "/login/callback",
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10; K) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/113.0.0.0 Mobile Safari/537.36"
                ),
            },
            allow_redirects=False,
        )
        r4.raise_for_status()
        location = r4.headers.get("Location")
        if not location:
            raise RuntimeError("No Location header after /login/callback")

        # STEP 5 – follow redirect, extract ?code= from Location
        _LOGGER.debug("PanasonicGLBAuthClient.login() - step 5")
        r5 = await self.session.get(
            urllib.parse.urljoin(AUTH_BASE, location),
            allow_redirects=False,
        )
        r5.raise_for_status()
        loc2 = r5.headers.get("Location")
        if not loc2:
            raise RuntimeError("No Location header with authorization code")

        parsed = urllib.parse.urlparse(loc2)
        params = urllib.parse.parse_qs(parsed.query)
        auth_code = params.get("code", [None])[0]
        if not auth_code:
            raise RuntimeError("No authorization code found in redirect")

        # STEP 6 – exchange code for tokens
        token_payload = {
            "scope": "openid",
            "client_id": OAUTH_CLIENT_ID,
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        }

        _LOGGER.debug("PanasonicGLBAuthClient.login() - step 6")
        r6 = await self.session.post(
            AUTH_BASE + "/oauth/token",
            json=token_payload,
            headers={"Auth0-Client": AUTH0_CLIENT},
            allow_redirects=False,
        )
        r6.raise_for_status()
        token_data = await r6.json()
        """
        Example token_data:
        {
            "access_token": "xxx",
            "refresh_token": "xxx",
            "id_token": "xxx",
            "scope": "openid mycfan.control offline_access",
            "expires_in": 86400,
            "token_type": "Bearer",
        }
        """

        return AuthToken(
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expiry=dt.now() + timedelta(seconds=token_data.get("expires_in", 3600)),
        )

    async def refresh_token(self):
        assert self.auth_token is not None

        _LOGGER.debug("PanasonicGLBAuthClient - refreshing access token")
        resp = await self.session.post(
            "https://authglb.digital.panasonic.com/oauth/token",
            headers={},
            json={
                "client_id": OAUTH_CLIENT_ID,
                "refresh_token": self.auth_token.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        token_data = await resp.json()

        self.auth_token.access_token = token_data["access_token"]
        self.auth_token.refresh_token = token_data["refresh_token"]
        self.auth_token.expiry = dt.now() + timedelta(
            seconds=token_data.get("expires_in", 3600)
        )


def generate_pkce_pair():
    verifier = base64url_encode(os.urandom(32))
    challenge = base64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def extract_state_from_location(location: str, default_state: str) -> str:
    parsed = urllib.parse.urlparse(location)
    params = urllib.parse.parse_qs(parsed.query)
    return params.get("state", [default_state])[0]


def get_csrf_from_cookies(session: aiohttp.ClientSession) -> str | None:
    """Extract CSRF token from session cookies."""
    for cookie in session.cookie_jar:
        if cookie.key == "_csrf":
            return cookie.value
    return None


def extract_hidden_inputs(html_text: str) -> dict:
    """Extract hidden input fields from HTML using regex and unescape values."""
    data = {}
    # Match: <input type="hidden" name="..." value="...">
    # This pattern handles both name-then-value and value-then-name orderings
    pattern = r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"|<input\s+type="hidden"\s+value="([^"]*)"\s+name="([^"]+)"'

    for match in re.finditer(pattern, html_text):
        if match.group(1):  # name-then-value pattern
            name = match.group(1)
            value = match.group(2)
        else:  # value-then-name pattern
            name = match.group(4)
            value = match.group(3)
        # HTML-unescape the value (e.g., &#34; -> ")
        data[name] = html.unescape(value)

    return data
