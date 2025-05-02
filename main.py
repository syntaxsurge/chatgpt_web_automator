from __future__ import annotations

import logging
import platform
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pyperclip
import undetected_chromedriver as uc
from fake_useragent import UserAgent
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import ENABLE_DEBUG, ROOT_DIR, env

# ──────────────────────────────────────────────────────────────
# 0.  Logging
# ──────────────────────────────────────────────────────────────

_logger = logging.getLogger(__name__)
if ENABLE_DEBUG and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")


# ──────────────────────────────────────────────────────────────
# 1.  Configurable constants (all timings in seconds)
# ──────────────────────────────────────────────────────────────


def _resolve_profile_dir() -> Path:
    """
    Return an absolute path for the Chrome user-data directory.

    If *CHROME_PROFILE_DIR* is relative, prefix it with *ROOT_DIR* so that the
    profile is found regardless of the current working directory.
    """
    raw = env("CHROME_PROFILE_DIR", "chromedata")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


CHROME_PROFILE_DIR: Path = _resolve_profile_dir()
AUTO_LOGIN: bool = env("AUTO_LOGIN", False, cast=bool)
HEADLESS_CHROME: bool = env("HEADLESS_CHROME", False, cast=bool)

EXPLICIT_WAIT_TIMEOUT: int = env("EXPLICIT_WAIT_TIMEOUT", 15, cast=int)
HUMAN_KEY_DELAY: tuple[float, float] = (
    env("HUMAN_KEY_DELAY_MIN", 0.08, cast=float),
    env("HUMAN_KEY_DELAY_MAX", 0.30, cast=float),
)
STREAM_SETTLE_TIME: float = env("STREAM_SETTLE_TIME", 0.8, cast=float)
POLL_INTERVAL: float = env("POLL_INTERVAL", 0.20, cast=float)
PASTE_CHUNK_SIZE: int = env("PASTE_CHUNK_SIZE", 50000, cast=int)

# —— typing-mode switch ——————————————————————————————————————
ACCEPTED_TYPING_MODES: set[str] = {"normal", "fast", "paste"}
TYPING_MODE: str = env("TYPING_MODE", "normal").lower()
if TYPING_MODE not in ACCEPTED_TYPING_MODES:
    TYPING_MODE = "normal"


# ──────────────────────────────────────────────────────────────
# 2.  DOM selectors
# ──────────────────────────────────────────────────────────────


class Locators:
    # Login page
    EMAIL_INPUT_ID = ":r1:-email"
    PASSWORD_INPUT_ID = ":re:-password"
    EMAIL_CONTINUE_XPATH = "//*[@id=':r1:']/div[2]/button"
    PASSWORD_CONTINUE_XPATH = "//*[@id=':re:']/div[2]/button"

    # Chat UI
    PROMPT_TEXTAREA_ID = "prompt-textarea"
    SUBMIT_BUTTON_ID = "composer-submit-button"

    # Assistant messages only (excludes user bubbles)
    ASSISTANT_BLOCK_XPATH = (
        "//div[@data-message-author-role='assistant']//div[contains(@class,'prose')]"
    )


# ──────────────────────────────────────────────────────────────
# 3.  Typed configuration containers
# ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Credentials:
    email: str = env("CHATGPT_EMAIL", "your_email@example.com")
    password: str = env("CHATGPT_PASSWORD", "your_password_here")


@dataclass(slots=True)
class ClientConfig:
    profile_dir: Path = CHROME_PROFILE_DIR
    headless: bool = HEADLESS_CHROME
    auto_login: bool = AUTO_LOGIN
    explicit_timeout: int = EXPLICIT_WAIT_TIMEOUT
    key_delay_range: tuple[float, float] = HUMAN_KEY_DELAY
    stream_settle: float = STREAM_SETTLE_TIME
    poll_interval: float = POLL_INTERVAL
    typing_mode: str = TYPING_MODE  # normal | fast | paste
    paste_chunk_size: int = PASTE_CHUNK_SIZE


# ──────────────────────────────────────────────────────────────
# 4.  Main helper class
# ──────────────────────────────────────────────────────────────


class ChatGPTWebAutomator:
    """
    Minimal wrapper around ChatGPT’s web UI that returns **complete** replies.

    Typing speed is governed by ``ClientConfig.typing_mode``:
      • normal – human-like per-character delay
      • fast   – per-character with zero delay
      • paste  – clipboard copy followed by Ctrl/⌘+V paste
    """

    HOME_URL = "https://chatgpt.com/"

    # —— life-cycle ——————————————————————————————————————

    def __init__(
            self,
            config: ClientConfig | None = None,
            creds: Credentials | None = None,
    ) -> None:
        self.cfg = config or ClientConfig()
        self.creds = creds or Credentials()
        self.driver = self._launch_driver()
        self.wait = WebDriverWait(self.driver, self.cfg.explicit_timeout)

        # Open landing page immediately (login only if asked).
        self.driver.get(self.HOME_URL)
        if self.cfg.auto_login:
            self._perform_login()

        # Track how many assistant bubbles are on-screen.
        self._prev_count = len(self._assistant_blocks())

    # —— navigation per request ————————————————————————————

    def open_new_chat(self, model: str | None = None) -> None:
        """
        Navigate to a fresh conversation, optionally targeting *model*.
        """
        url = self.HOME_URL
        if model:
            url = f"{url}?model={model}"
        self.driver.get(url)

        # Ensure prompt box present then reset block counter.
        self._wait_visible(By.ID, Locators.PROMPT_TEXTAREA_ID)
        self._prev_count = len(self._assistant_blocks())

    # —— public API ———————————————————————————————————————

    def send_message(self, prompt: str) -> List[str]:
        """
        Type *prompt*, press Send, then block until assistant reply completes.
        Returns one ``str`` per assistant message block.
        """
        textarea = self._wait_visible(By.ID, Locators.PROMPT_TEXTAREA_ID)
        self._human_type(textarea, prompt)
        self._click(By.ID, Locators.SUBMIT_BUTTON_ID)

        self.wait.until(lambda _: len(self._assistant_blocks()) > self._prev_count)
        self._wait_stream_finished(self._prev_count)

        blocks = self._assistant_blocks()
        new_blocks = blocks[self._prev_count:]
        self._prev_count = len(blocks)
        return [blk.text.strip() for blk in new_blocks]

    def quit(self) -> None:
        """Close Chrome and wipe any *temporary* profile generated."""
        try:
            self.driver.quit()
        finally:
            if self.cfg.profile_dir.exists() and "chatgpt_profile_" in str(
                    self.cfg.profile_dir
            ):
                shutil.rmtree(self.cfg.profile_dir, ignore_errors=True)

    # Allow use as a context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.quit()

    # —— private helpers ————————————————————————————————

    # 4-A. WebDriver bootstrap
    # ------------------------

    def _launch_driver(self) -> Chrome:
        ua_string = UserAgent().random

        profile = self.cfg.profile_dir
        profile.mkdir(parents=True, exist_ok=True)

        opts = ChromeOptions()
        opts.add_argument(f"--user-agent={ua_string}")
        opts.add_argument(f"--user-data-dir={profile}")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        if self.cfg.headless:
            opts.add_argument("--headless=new")

        driver: Chrome = uc.Chrome(options=opts, enable_cdp_events=True)
        driver.execute_script(
            "Object.defineProperty(navigator,'webdriver',{get:() => undefined})"
        )
        return driver

    # 4-B. Optional login
    # -------------------

    def _perform_login(self) -> None:
        print("🔐  Logging in…")
        email = self._wait_visible(By.ID, Locators.EMAIL_INPUT_ID)
        self._human_type(email, self.creds.email)
        self._click(By.XPATH, Locators.EMAIL_CONTINUE_XPATH)

        pwd = self._wait_visible(By.ID, Locators.PASSWORD_INPUT_ID)
        self._human_type(pwd, self.creds.password)
        self._click(By.XPATH, Locators.PASSWORD_CONTINUE_XPATH)
        print("✅  Login successful.")

    # 4-C. Streaming detection
    # ------------------------

    def _wait_stream_finished(self, start_index: int) -> None:
        """
        Wait until ChatGPT has fully streamed its reply.
        """
        last_snapshot = ""
        stable_since = time.monotonic()

        while True:
            try:
                blocks = self._assistant_blocks()[start_index:]
                joined = "\n".join(blk.text for blk in blocks)
            except StaleElementReferenceException:
                time.sleep(self.cfg.poll_interval / 2)
                continue

            if not joined.strip():
                last_snapshot = joined
                stable_since = time.monotonic()
                time.sleep(self.cfg.poll_interval)
                continue

            has_cursor = joined.endswith("▍")
            if joined == last_snapshot and not has_cursor:
                if time.monotonic() - stable_since >= self.cfg.stream_settle:
                    break
            else:
                last_snapshot = joined
                stable_since = time.monotonic()

            time.sleep(self.cfg.poll_interval)

    # 4-D. Selenium wrappers
    # ----------------------

    def _assistant_blocks(self):
        return self.driver.find_elements(By.XPATH, Locators.ASSISTANT_BLOCK_XPATH)

    def _wait_visible(self, by: By | str, locator: str):
        return self.wait.until(EC.visibility_of_element_located((str(by), locator)))

    def _click(self, by: By | str, locator: str) -> None:
        self.wait.until(EC.element_to_be_clickable((str(by), locator))).click()

    # —— input helpers ————————————————————————————————

    def _human_type(self, element, text: str) -> None:
        """
        Insert *text* into *element* according to typing mode.

        • normal – human-like per character delay
        • fast   – blast entire text via send_keys
        • paste  – copy to clipboard then paste with Ctrl/⌘+V
        """
        mode = self.cfg.typing_mode

        # —— paste mode —————————————————————————————
        if mode == "paste":
            if ENABLE_DEBUG:
                _logger.debug("Pasting via clipboard (%d chars)", len(text))

            # Split huge inputs to avoid OS clipboard limits
            chunk_size = max(1, self.cfg.paste_chunk_size)
            ctrl_key = Keys.COMMAND if platform.system() == "Darwin" else Keys.CONTROL

            # Ensure textarea has focus
            element.click()
            # Clear any existing content
            element.send_keys(ctrl_key, "a")
            element.send_keys(Keys.DELETE)

            for i in range(0, len(text), chunk_size):
                chunk = text[i: i + chunk_size]
                pyperclip.copy(chunk)
                # Use ActionChains to ensure key down/up sequence
                ActionChains(self.driver).key_down(ctrl_key).send_keys("v").key_up(
                    ctrl_key
                ).perform()
                time.sleep(0.05)  # allow React state update
            return

        # Helper for other modes
        def _send(ch: str) -> None:
            if ch == "\n":
                element.send_keys(Keys.SHIFT, Keys.ENTER)
            else:
                element.send_keys(ch)

        # —— fast mode ————————————————————————————
        if mode == "fast":
            element.send_keys(text)
            return

        # —— normal mode ——————————————————————————
        lo, hi = self.cfg.key_delay_range
        for ch in text:
            _send(ch)
            time.sleep(random.uniform(lo, hi))


# ──────────────────────────────────────────────────────────────
# 5.  Simple CLI for manual testing
# ──────────────────────────────────────────────────────────────


def main() -> None:
    try:
        with ChatGPTWebAutomator() as bot:
            print("🤖  ChatGPT browser ready (Ctrl-C to quit)\n")
            while True:
                prompt = input("You : ")
                bot.open_new_chat(model="o3")  # manual test
                for chunk in bot.send_message(prompt):
                    print(f"Bot : {chunk}\n")
    except KeyboardInterrupt:
        print("\n✋  Session ended.")


if __name__ == "__main__":
    main()
