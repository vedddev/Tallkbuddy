"""Explicit, non-destructive staging HTTP/WebSocket security smoke test.

Requires an existing dedicated staging test account. Never prints credentials or cookies.
This is not a browser or live-audio test.
"""

import os
import sys
from urllib.parse import urlsplit

import httpx
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect


def _check(name: str, passed: bool) -> None:
    print(f"{'PASS' if passed else 'FAIL'} {name}")
    if not passed:
        raise RuntimeError(f"Staging check failed: {name}")


def main() -> int:
    origin = os.getenv("STAGING_ORIGIN", "").rstrip("/")
    email = os.getenv("STAGING_TEST_EMAIL", "")
    password = os.getenv("STAGING_TEST_PASSWORD", "")
    parsed = urlsplit(origin)
    if (os.getenv("STAGING_CONFIRM") != "1" or parsed.scheme != "https" or not parsed.hostname
            or parsed.path or parsed.query or parsed.fragment or not email or not password):
        print("NOT VERIFIED: set STAGING_CONFIRM=1, STAGING_ORIGIN, and dedicated staging test account variables.")
        return 2

    try:
        with httpx.Client(base_url=origin, timeout=10, follow_redirects=False) as client:
            frontend = client.get("/")
            _check("frontend index", frontend.status_code == 200 and "<html" in frontend.text.lower())
            _check("liveness", client.get("/api/health").status_code == 200)
            _check("database readiness", client.get("/api/health/ready").status_code == 200)
            _check("unauthorized API", client.get("/api/auth/me").status_code == 401)
            untrusted = client.post("/api/auth/register", json={}, headers={"Origin": "https://untrusted.invalid"})
            _check("untrusted HTTP Origin", untrusted.status_code == 403)
            preflight = client.options("/api/auth/register", headers={
                "Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "POST",
            })
            _check("untrusted CORS preflight", preflight.status_code == 400)

            login = client.post("/api/auth/login", json={"email": email, "password": password},
                                headers={"Origin": origin})
            _check("dedicated account login", login.status_code == 200)
            session_cookie = client.cookies.get("talkbuddy_session")
            csrf_cookie = client.cookies.get("talkbuddy_csrf")
            cookie_headers = login.headers.get_list("set-cookie")
            _check("secure HttpOnly session cookie", bool(session_cookie) and any(
                "talkbuddy_session=" in value and "httponly" in value.lower() and "secure" in value.lower()
                for value in cookie_headers))
            _check("CSRF cookie", bool(csrf_cookie))
            _check("authenticated API", client.get("/api/auth/me").status_code == 200)
            _check("missing CSRF rejected", client.post("/api/auth/logout", headers={"Origin": origin}).status_code == 403)

            ws_url = "wss://" + parsed.netloc + "/ws/translate"
            cookie = f"talkbuddy_session={session_cookie}"
            with connect(ws_url, origin=origin, additional_headers={"Cookie": cookie},
                         open_timeout=10, close_timeout=5) as socket:
                socket.send('{"type":"start","target_language":"hi","audio_format":"wav"}')
                _check("authenticated WSS", '"type":"ready"' in socket.recv(timeout=10).replace(" ", ""))
                socket.send('{"type":"stop"}')
            try:
                with connect(ws_url, origin="https://untrusted.invalid", additional_headers={"Cookie": cookie},
                             open_timeout=10, close_timeout=5):
                    rejected = False
            except InvalidStatus as exc:
                rejected = exc.response.status_code == 403
            _check("untrusted WSS Origin", rejected)

            logout = client.post("/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": csrf_cookie})
            _check("logout", logout.status_code == 200)
            _check("logout revokes session", client.get(
                "/api/auth/me", headers={"Cookie": cookie}
            ).status_code == 401)
    except Exception as exc:
        print(f"FAIL staging smoke ({type(exc).__name__}); inspect private server logs and configuration.")
        return 1
    print("PASS staging HTTP/WSS smoke; browser audio, provider output, and backup remain separate checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
