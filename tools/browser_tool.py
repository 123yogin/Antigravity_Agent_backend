"""
Browser Tool — Playwright-based browser automation.

Capabilities: navigate, scrape text, screenshot, click, fill forms, evaluate JS.
Used by the operator for web research, testing, and automation tasks.
"""

import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("antigravity.browser_tool")


@dataclass
class BrowserResult:
    """Result of a browser action."""
    action: str
    success: bool
    message: str
    data: str = ""

    def summary(self) -> str:
        status = "✅" if self.success else "❌"
        out = f"{status} [BROWSER:{self.action.upper()}] {self.message}"
        if self.data and len(self.data) < 500:
            out += f"\n  Data: {self.data[:500]}"
        return out


class BrowserTool:
    """
    Browser automation via Playwright.
    
    Uses async Playwright under the hood but exposes a sync interface
    for easy integration with the agent loop.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._page = None
        self._playwright = None

    async def _ensure_browser(self):
        """Lazily launch browser on first use."""
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=self.headless)
                self._page = await self._browser.new_page()
                logger.info("Browser launched (headless=%s)", self.headless)
            except Exception as e:
                logger.error(f"Failed to launch browser: {e}")
                raise

    async def _navigate(self, url: str) -> BrowserResult:
        """Navigate to a URL."""
        await self._ensure_browser()
        try:
            response = await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else "unknown"
            title = await self._page.title()
            return BrowserResult("navigate", True, f"Loaded: {title} (HTTP {status})", data=url)
        except Exception as e:
            return BrowserResult("navigate", False, f"Navigation failed: {str(e)}")

    async def _get_text(self) -> BrowserResult:
        """Extract visible text content from the current page."""
        await self._ensure_browser()
        try:
            text = await self._page.inner_text("body")
            # Truncate very long pages
            if len(text) > 5000:
                text = text[:5000] + "\n... (truncated)"
            return BrowserResult("get_text", True, f"Extracted {len(text)} chars", data=text)
        except Exception as e:
            return BrowserResult("get_text", False, f"Text extraction failed: {str(e)}")

    async def _screenshot(self, path: str = "screenshot.png") -> BrowserResult:
        """Take a screenshot of the current page."""
        await self._ensure_browser()
        try:
            save_path = Path(path).resolve()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(save_path), full_page=True)
            return BrowserResult("screenshot", True, f"Saved to {save_path}", data=str(save_path))
        except Exception as e:
            return BrowserResult("screenshot", False, f"Screenshot failed: {str(e)}")

    async def _click(self, selector: str) -> BrowserResult:
        """Click an element on the page."""
        await self._ensure_browser()
        try:
            await self._page.click(selector, timeout=10000)
            return BrowserResult("click", True, f"Clicked: {selector}")
        except Exception as e:
            return BrowserResult("click", False, f"Click failed on '{selector}': {str(e)}")

    async def _fill(self, selector: str, value: str) -> BrowserResult:
        """Fill a form field."""
        await self._ensure_browser()
        try:
            await self._page.fill(selector, value, timeout=10000)
            return BrowserResult("fill", True, f"Filled '{selector}' with value")
        except Exception as e:
            return BrowserResult("fill", False, f"Fill failed on '{selector}': {str(e)}")

    async def _evaluate(self, js_code: str) -> BrowserResult:
        """Evaluate JavaScript in the page context."""
        await self._ensure_browser()
        try:
            result = await self._page.evaluate(js_code)
            return BrowserResult("evaluate", True, "JS executed", data=str(result))
        except Exception as e:
            return BrowserResult("evaluate", False, f"JS evaluation failed: {str(e)}")

    async def _close(self) -> BrowserResult:
        """Close the browser."""
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._browser = None
            self._page = None
            self._playwright = None
            return BrowserResult("close", True, "Browser closed")
        except Exception as e:
            return BrowserResult("close", False, f"Close failed: {str(e)}")

    # ─── Sync wrappers ──────────────────────────────────────────────────────

    def _run_async(self, coro):
        """Run an async coroutine from sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an existing event loop — use nest_asyncio pattern
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    def navigate(self, url: str) -> BrowserResult:
        return self._run_async(self._navigate(url))

    def get_text(self) -> BrowserResult:
        return self._run_async(self._get_text())

    def screenshot(self, path: str = "screenshot.png") -> BrowserResult:
        return self._run_async(self._screenshot(path))

    def click(self, selector: str) -> BrowserResult:
        return self._run_async(self._click(selector))

    def fill(self, selector: str, value: str) -> BrowserResult:
        return self._run_async(self._fill(selector, value))

    def evaluate(self, js_code: str) -> BrowserResult:
        return self._run_async(self._evaluate(js_code))

    def close(self) -> BrowserResult:
        return self._run_async(self._close())

    def execute(self, action: str, **kwargs) -> BrowserResult:
        """Dispatch a browser action by name."""
        actions = {
            "navigate": lambda: self.navigate(kwargs.get("url", "")),
            "get_text": lambda: self.get_text(),
            "screenshot": lambda: self.screenshot(kwargs.get("path", "screenshot.png")),
            "click": lambda: self.click(kwargs.get("selector", "")),
            "fill": lambda: self.fill(kwargs.get("selector", ""), kwargs.get("value", "")),
            "evaluate": lambda: self.evaluate(kwargs.get("code", "")),
            "close": lambda: self.close(),
        }
        handler = actions.get(action)
        if not handler:
            return BrowserResult(action, False, f"Unknown browser action: {action}")
        return handler()


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    console = Console()

    tool = BrowserTool(headless=True)
    
    console.print("\n[bold cyan]Testing browser navigation:[/]")
    result = tool.navigate("https://httpbin.org/html")
    console.print(result.summary())

    console.print("\n[bold cyan]Extracting text:[/]")
    result = tool.get_text()
    console.print(result.summary())

    tool.close()
    console.print("\n[bold green]Browser tool test complete.[/]")
