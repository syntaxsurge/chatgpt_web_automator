from __future__ import annotations

import logging
import random
import shutil
import time
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

from config import ENABLE_DEBUG
from .locators import Locators
from .models import ClientConfig, Credentials

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

_logger = logging.getLogger(__name__)
if ENABLE_DEBUG and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")


# ──────────────────────────────────────────────────────────────
# Public class
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

    # —— life-cycle ————————————————————————————————————————————

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
        url = self.HOME_URL if not model else f"{self.HOME_URL}?model={model}"
        self.driver.get(url)

        # Ensure prompt box is present then reset block counter.
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

        # Wait until either a normal assistant block appears or an error bubble is rendered
        self.wait.until(
            lambda _:
            len(self._assistant_blocks()) > self._prev_count
            or self._error_blocks()
        )

        # If an error bubble is present, return its text immediately
        if self._error_blocks():
            error_blocks = self._error_blocks()
            # Do not increment _prev_count so next interaction starts clean
            return [blk.text.strip() for blk in error_blocks]

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

    # 1. WebDriver bootstrap
    # ----------------------

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

    # 2. Optional login
    # -----------------

    def _perform_login(self) -> None:
        print("🔐  Logging in…")
        email = self._wait_visible(By.ID, Locators.EMAIL_INPUT_ID)
        self._human_type(email, self.creds.email)
        self._click(By.XPATH, Locators.EMAIL_CONTINUE_XPATH)

        pwd = self._wait_visible(By.ID, Locators.PASSWORD_INPUT_ID)
        self._human_type(pwd, self.creds.password)
        self._click(By.XPATH, Locators.PASSWORD_CONTINUE_XPATH)
        print("✅  Login successful.")

    # 3. Streaming detection
    # ----------------------

    def _wait_stream_finished(self, start_index: int) -> None:
        """
        Wait until ChatGPT has fully streamed its reply.

        A reply is considered *complete* only after **both** of the following
        are true:

        1.  The UI stop button is no longer present – indicating ChatGPT has
            stopped generating; **and**
        2.  The assistant text has remained unchanged for
            ``ClientConfig.stream_settle`` seconds without the trailing cursor.

        This dual check prevents prematurely treating a reply as finished when
        the text happens to pause mid-stream.
        """
        last_snapshot = ""
        stable_since = time.monotonic()

        while True:
            # Abort immediately if an error bubble is detected
            if self._error_blocks():
                break
            # Presence of the stop button means streaming is still in progress.
            streaming_busy = bool(
                self.driver.find_elements(By.CSS_SELECTOR, Locators.STOP_BUTTON_SELECTOR)
            )

            try:
                blocks = self._assistant_blocks()[start_index:]
                joined = "\n".join(blk.text for blk in blocks)
            except StaleElementReferenceException:
                time.sleep(self.cfg.poll_interval / 2)
                continue

            # Reset stability timer on empty snapshots (UI re-render, etc.).
            if not joined.strip():
                last_snapshot = joined
                stable_since = time.monotonic()
                time.sleep(self.cfg.poll_interval)
                continue

            has_cursor = joined.endswith("▍")

            # Any change in text, visible cursor, or ongoing streaming resets timer.
            if streaming_busy or has_cursor or joined != last_snapshot:
                last_snapshot = joined
                stable_since = time.monotonic()
                time.sleep(self.cfg.poll_interval)
                continue

            # No stop button, no cursor, and text stable long enough → done.
            if time.monotonic() - stable_since >= self.cfg.stream_settle:
                break

            time.sleep(self.cfg.poll_interval)

    # 4. Selenium wrappers
    # --------------------

    def _assistant_blocks(self):
        return self.driver.find_elements(By.XPATH, Locators.ASSISTANT_BLOCK_XPATH)

    def _error_blocks(self):
        """Return any visible ChatGPT error bubbles."""
        return self.driver.find_elements(By.XPATH, Locators.ERROR_BLOCK_XPATH)

    def _wait_visible(self, by: By | str, locator: str):
        return self.wait.until(EC.visibility_of_element_located((str(by), locator)))

    def _click(self, by: By | str, locator: str) -> None:
        self.wait.until(EC.element_to_be_clickable((str(by), locator))).click()

    # 5. Input helpers
    # ----------------

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
            ctrl_key = self.cfg.ctrl_or_cmd()

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
