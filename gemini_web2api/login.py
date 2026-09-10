"""Capture Gemini Web cookies after a real Google (Gmail) sign-in.

Google OAuth / AI Studio keys are not Gemini Web cookies. SID, SAPISID, and
__Secure-1PSID are HttpOnly cookies on google.com — this helper never asks you
to type a Gmail password into gemini-web2api.
"""
from __future__ import annotations

import json
import os
import sys
import time

EXPORT_ORDER = [
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "LSID",
    "OSID",
    "SIDCC",
    "AEC",
    "NID",
    "COMPASS",
    "__Secure-1PAPISID",
    "__Secure-1PSID",
    "__Secure-1PSIDTS",
    "__Secure-1PSIDCC",
    "__Secure-1PSIDRTS",
    "__Secure-3PAPISID",
    "__Secure-3PSID",
    "__Secure-3PSIDTS",
    "__Secure-3PSIDCC",
    "__Secure-3PSIDRTS",
    "__Secure-OSID",
    "__Host-1PLSID",
    "__Host-3PLSID",
]

CORE_REQUIRED = ("SAPISID",)
SESSION_ALTERNATIVES = ("__Secure-1PSID", "__Secure-3PSID", "SID")
LOGIN_URL = (
    "https://accounts.google.com/ServiceLogin?hl=en"
    "&continue=https%3A%2F%2Fgemini.google.com%2Fapp"
)


def _domain_score(domain: str) -> int:
    domain = (domain or "").lower().lstrip(".")
    if domain == "google.com":
        return 120
    if domain == "gemini.google.com":
        return 100
    if domain == "accounts.google.com":
        return 80
    if domain.endswith(".google.com") or domain.endswith("google.com"):
        return 40
    return 0


def cookies_to_header(cookies) -> str:
    """Build a Cookie header from Playwright / Chrome cookie dicts. Fake values only in tests."""
    selected = {}
    scores = {}
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if name not in EXPORT_ORDER or not value:
            continue
        score = _domain_score(cookie.get("domain") or "")
        if name not in selected or score > scores.get(name, -1):
            selected[name] = value
            scores[name] = score
    return "; ".join(f"{name}={selected[name]}" for name in EXPORT_ORDER if name in selected)


def header_is_ready(header: str) -> bool:
    names = set(cookie_names(header))
    if "SAPISID" not in names:
        return False
    return any(name in names for name in SESSION_ALTERNATIVES)


def cookie_names(header: str) -> list:
    names = []
    for part in (header or "").split(";"):
        if "=" in part:
            names.append(part.split("=", 1)[0].strip())
    return names


def cookie_from_auth_json(data) -> str:
    if not isinstance(data, dict):
        raise ValueError("gemini-auth.json must be a JSON object")
    cookie = data.get("cookie")
    if isinstance(cookie, str) and "=" in cookie:
        return cookie.strip().replace("\n", " ")
    cookies = data.get("cookies")
    if isinstance(cookies, list):
        header = cookies_to_header(cookies)
        if header:
            return header
    raise ValueError("gemini-auth.json has no cookie field")


def write_cookie_file(path: str, header: str) -> str:
    if not header_is_ready(header):
        raise ValueError(
            "Cookie string is missing SAPISID and a session cookie "
            "(__Secure-1PSID, __Secure-3PSID, or SID)"
        )
    dest = os.path.abspath(path)
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(header.strip() + "\n")
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    return dest


def _playwright_missing_message() -> str:
    return (
        "Playwright is not installed. On your own computer run:\n"
        "  pip install playwright && playwright install chromium\n"
        "  python -m gemini_web2api login\n\n"
        "On Render, paste GEMINI_COOKIE in the playground sidebar or set it "
        "in the dashboard. This site never asks for your Google password."
    )


def _no_display_message() -> str:
    return (
        "No desktop display. Google sign-in needs a real browser window.\n"
        "Run `python -m gemini_web2api login` on your computer, or paste "
        "GEMINI_COOKIE in the playground sidebar.\n"
        "Do not paste a Gmail password into this server."
    )


def run_browser_login(timeout: int = 300) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(_playwright_missing_message()) from exc

    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError(_no_display_message())

    print("Opening Google sign-in for Gemini. Use your Gmail account in that window.")
    print("gemini-web2api never sees your password.")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        deadline = time.time() + max(30, int(timeout))
        header = ""
        try:
            while time.time() < deadline:
                header = cookies_to_header(context.cookies())
                url = page.url or ""
                if header_is_ready(header) and "gemini.google.com" in url:
                    break
                time.sleep(1)
            else:
                if not header_is_ready(header):
                    raise TimeoutError(
                        "Timed out waiting for Gmail sign-in. Finish login in the "
                        "browser window, then retry."
                    )
        finally:
            browser.close()
    return header


def run_login(output: str = "cookie.txt", from_json: str | None = None, timeout: int = 300) -> int:
    try:
        if from_json:
            with open(from_json, encoding="utf-8") as handle:
                data = json.load(handle)
            header = cookie_from_auth_json(data)
        else:
            header = run_browser_login(timeout=timeout)
        dest = write_cookie_file(output, header)
    except FileNotFoundError:
        print(f"File not found: {from_json}", file=sys.stderr)
        return 1
    except (ValueError, TimeoutError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote {dest} (do not commit this file).")
    print("Cookie names:", ", ".join(cookie_names(header)))
    print("Set GEMINI_COOKIE in the Render dashboard, or run with --cookie-file", dest)
    return 0
