from __future__ import annotations

"""Residential-proxy Playwright launcher with fingerprint / WebRTC hardening.

REFUSED: Upwork / Fiverr / marketplace login automation.
Proxy is for allowed-source or user-driven sessions only — egress must match
home country (default UZ) so datacenter IPs never touch those flows.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.core.config import settings

# Hard refuse — never launch stealth browser against marketplace auth surfaces
_MARKETPLACE_HOST_FRAGMENTS = (
    "upwork.com",
    "fiverr.com",
    "freelancer.com",
    "toptal.com",
    "peopleperhour.com",
)


class MarketplaceAutomationRefused(RuntimeError):
    """Raised if a caller attempts marketplace login/scrape automation."""


@dataclass(frozen=True)
class ProxyConfig:
    server: str
    username: Optional[str] = None
    password: Optional[str] = None
    country: str = "UZ"


def assert_url_allowed(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    for frag in _MARKETPLACE_HOST_FRAGMENTS:
        if frag in host:
            raise MarketplaceAutomationRefused(
                f"Marketplace automation refused for host '{host}'. "
                "The Sterling Syndicate never logs into Upwork/Fiverr."
            )


def residential_proxy_config() -> Optional[ProxyConfig]:
    """Build proxy config from env. Returns None if proxy not configured."""
    server = (settings.residential_proxy_url or "").strip()
    if not server:
        if settings.residential_proxy_required:
            raise RuntimeError(
                "RESIDENTIAL_PROXY_REQUIRED=true but RESIDENTIAL_PROXY_URL is empty. "
                "Configure a Uzbekistan residential proxy before launching Playwright."
            )
        return None
    return ProxyConfig(
        server=server,
        username=settings.residential_proxy_username or None,
        password=settings.residential_proxy_password or None,
        country=(settings.residential_proxy_country or "UZ").upper(),
    )


def playwright_proxy_dict(cfg: ProxyConfig) -> Dict[str, str]:
    d: Dict[str, str] = {"server": cfg.server}
    if cfg.username:
        d["username"] = cfg.username
    if cfg.password:
        d["password"] = cfg.password
    return d


# Injected before any page script — kill WebRTC + common headless leaks
_STEALTH_INIT_SCRIPT = r"""
(() => {
  // WebRTC leak defense — prevent local/datacenter IP discovery
  const noop = () => {};
  const fakePC = function() { throw new Error('WebRTC disabled'); };
  try {
    Object.defineProperty(window, 'RTCPeerConnection', { get: () => fakePC });
    Object.defineProperty(window, 'webkitRTCPeerConnection', { get: () => fakePC });
    Object.defineProperty(window, 'mozRTCPeerConnection', { get: () => fakePC });
  } catch (e) {}
  try {
    if (navigator.mediaDevices) {
      navigator.mediaDevices.getUserMedia = () => Promise.reject(new Error('disabled'));
      navigator.mediaDevices.enumerateDevices = () => Promise.resolve([]);
    }
  } catch (e) {}

  // Headless / automation fingerprints
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (e) {}
  try {
    window.chrome = window.chrome || { runtime: {} };
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'uz'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
  } catch (e) {}

  // Disable WebGL vendor leak commonly used for bot scoring (best-effort)
  try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
      if (param === 37445) return 'Intel Inc.';
      if (param === 37446) return 'Intel Iris OpenGL Engine';
      return getParameter.call(this, param);
    };
  } catch (e) {}
})();
"""


def stealth_init_script() -> str:
    return _STEALTH_INIT_SCRIPT


def launch_kwargs(*, headless: Optional[bool] = None) -> Dict[str, Any]:
    """Args for playwright.chromium.launch / launch_persistent_context."""
    cfg = residential_proxy_config()
    headed = settings.playwright_headed if headless is None else not headless
    kwargs: Dict[str, Any] = {
        "headless": not headed,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-webrtc",
            "--enforce-webrtc-ip-permission-check",
            "--force-webrtc-ip-permission-check",
        ],
    }
    if cfg is not None:
        kwargs["proxy"] = playwright_proxy_dict(cfg)
    return kwargs


async def open_stealth_page(
    playwright: Any,
    *,
    url: str = "",
    headless: Optional[bool] = None,
) -> Any:
    """Launch Chromium via residential proxy + stealth init. Returns Page.

    Caller owns browser lifecycle (browser.close()). Marketplace URLs raise.
    """
    if url:
        assert_url_allowed(url)

    browser = await playwright.chromium.launch(**launch_kwargs(headless=headless))
    context = await browser.new_context(
        locale="en-US",
        timezone_id=settings.playwright_timezone or "Asia/Tashkent",
        viewport={"width": 1366, "height": 768},
        user_agent=(
            settings.playwright_user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        ),
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,uz;q=0.8"},
    )
    await context.add_init_script(stealth_init_script())
    page = await context.new_page()
    # Attach browser for cleanup convenience
    page._pp_browser = browser  # type: ignore[attr-defined]
    if url:
        await page.goto(url, wait_until="domcontentloaded")
    return page


def sync_launch_browser(playwright: Any, *, headless: Optional[bool] = None) -> Any:
    """Sync API variant for non-async callers."""
    return playwright.chromium.launch(**launch_kwargs(headless=headless))


def sync_new_stealth_context(browser: Any) -> Any:
    context = browser.new_context(
        locale="en-US",
        timezone_id=settings.playwright_timezone or "Asia/Tashkent",
        viewport={"width": 1366, "height": 768},
        user_agent=(
            settings.playwright_user_agent
            or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        ),
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9,uz;q=0.8"},
    )
    context.add_init_script(stealth_init_script())
    return context


def proxy_status() -> Dict[str, Any]:
    cfg = None
    err = None
    try:
        cfg = residential_proxy_config()
    except Exception as exc:
        err = str(exc)
    return {
        "configured": cfg is not None,
        "required": settings.residential_proxy_required,
        "country": (settings.residential_proxy_country or "UZ").upper(),
        "server_set": bool(settings.residential_proxy_url),
        "webrtc_disabled": True,
        "marketplace_automation": "refused",
        "error": err,
    }
