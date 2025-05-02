"""
chatgpt_web_automator.py
------------------------

Minimal Selenium wrapper around ChatGPT’s public UI that *reliably*
captures complete, fully-streamed assistant replies.

Author   : <your-name>
Updated  : 2025-05-03
Python   : 3.12+
"""

from __future__ import annotations

import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from typing import List

import undetected_chromedriver as uc
from fake_useragent import UserAgent
from selenium.common.exceptions import StaleElementReferenceException  # NEW ✨
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ──────────────────────────────────────────────────────────────
# 1.  Tweak-me constants (all timings in seconds)
# ──────────────────────────────────────────────────────────────

CHROME_PROFILE_DIR: Path = Path("chromedata")  # existing folder with valid cookies
AUTO_LOGIN: bool = False                       # set True if you *must* login each run
HEADLESS_CHROME: bool = False                  # True => run invisibly

EXPLICIT_WAIT_TIMEOUT = 15                     # used by Selenium waits
HUMAN_KEY_DELAY = (0.08, 0.30)                 # random delay per keystroke
STREAM_SETTLE_TIME = 0.8                       # how long the text must stay unchanged
POLL_INTERVAL = 0.20                           # how often we re-read the DOM during streaming


# ──────────────────────────────────────────────────────────────
# 2.  DOM selectors in one place
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

    # *** Only assistant messages (excludes user bubbles) ***
    ASSISTANT_BLOCK_XPATH = (
        "//div[@data-message-author-role='assistant']//div[contains(@class,'prose')]"
    )


# ──────────────────────────────────────────────────────────────
# 3.  Typed configuration containers
# ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Credentials:
    email: str = "your_email@example.com"
    password: str = "your_password_here"


@dataclass(slots=True)
class ClientConfig:
    profile_dir: Path = CHROME_PROFILE_DIR
    headless: bool = HEADLESS_CHROME
    auto_login: bool = AUTO_LOGIN
    explicit_timeout: int = EXPLICIT_WAIT_TIMEOUT
    key_delay_range: tuple[float, float] = HUMAN_KEY_DELAY
    stream_settle: float = STREAM_SETTLE_TIME
    poll_interval: float = POLL_INTERVAL


# ──────────────────────────────────────────────────────────────
# 4.  Main helper class
# ──────────────────────────────────────────────────────────────

class ChatGPTWebAutomator:
    """Tiny wrapper around ChatGPT’s website that returns *complete* replies."""

    HOME_URL = "https://chatgpt.com/"

    # —— life-cycle ————————————————————————————

    def __init__(
        self,
        config: ClientConfig | None = None,
        creds: Credentials | None = None,
    ) -> None:
        self.cfg = config or ClientConfig()
        self.creds = creds or Credentials()
        self.driver = self._launch_driver()
        self.wait = WebDriverWait(self.driver, self.cfg.explicit_timeout)

        # Open the landing page immediately (login only if asked).
        self.driver.get(self.HOME_URL)
        if self.cfg.auto_login:
            self._perform_login()

        # Track how many assistant bubbles are on-screen.
        self._prev_count = len(self._assistant_blocks())

    # —— NEW: explicit navigation per request ————————————————

    def open_new_chat(self, model: str | None = None) -> None:
        """
        Navigate to a **fresh** ChatGPT conversation, optionally targeting
        a specific model (e.g. ``model='o3'`` ➜
        ``https://chatgpt.com/?model=o3``).

        This is invoked at the start of *every* queued request so we never
        type into a stale conversation.
        """
        url = self.HOME_URL
        if model:
            url = f"{url}?model={model}"
        self.driver.get(url)

        # Wait until the prompt box is present – this guarantees the page is
        # ready for input – and reset the internal message counter.
        self._wait_visible(By.ID, Locators.PROMPT_TEXTAREA_ID)
        self._prev_count = len(self._assistant_blocks())

    # —— public API ————————————————————————————

    def send_message(self, prompt: str) -> List[str]:
        """
        Type *prompt*, press Send, then **block** until any *new* assistant
        messages have completely streamed.  Returns one str per new block.
        """
        # 1) enter the prompt + click send
        textarea = self._wait_visible(By.ID, Locators.PROMPT_TEXTAREA_ID)
        self._human_type(textarea, prompt)
        self._click(By.ID, Locators.SUBMIT_BUTTON_ID)

        # 2) wait for at least one brand-new assistant bubble
        self.wait.until(lambda _: len(self._assistant_blocks()) > self._prev_count)

        # 3) now poll until all *new* bubbles stop changing
        self._wait_stream_finished(self._prev_count)

        # 4) slice out only the fresh blocks and update the cursor
        blocks = self._assistant_blocks()
        new_blocks = blocks[self._prev_count:]
        self._prev_count = len(blocks)

        return [blk.text.strip() for blk in new_blocks]

    def quit(self) -> None:
        """Close Chrome and wipe any *temporary* profile we generated."""
        try:
            self.driver.quit()
        finally:
            if self.cfg.profile_dir.exists() and "chatgpt_profile_" in str(
                self.cfg.profile_dir
            ):
                shutil.rmtree(self.cfg.profile_dir, ignore_errors=True)

    # enable *with* … syntax
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.quit()

    # —— private helpers —————————————————————————

    # 4-A.  WebDriver bootstrap
    # -------------------------

    def _launch_driver(self) -> Chrome:
        ua_string = UserAgent().random
        profile = (
            self.cfg.profile_dir
            if self.cfg.profile_dir.exists()
            else Path(mkdtemp(prefix="chatgpt_profile_"))
        )
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
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver

    # 4-B.  Login flow (optional)
    # ---------------------------

    def _perform_login(self) -> None:
        print("🔐  Logging in…")
        email = self._wait_visible(By.ID, Locators.EMAIL_INPUT_ID)
        self._human_type(email, self.creds.email)
        self._click(By.XPATH, Locators.EMAIL_CONTINUE_XPATH)

        pwd = self._wait_visible(By.ID, Locators.PASSWORD_INPUT_ID)
        self._human_type(pwd, self.creds.password)
        self._click(By.XPATH, Locators.PASSWORD_CONTINUE_XPATH)
        print("✅  Login successful.")

    # 4-C.  Streaming detection
    # -------------------------

    def _wait_stream_finished(self, start_index: int) -> None:
        """
        Poll the DOM until *all* assistant blocks from *start_index* onward
        stay unchanged for cfg.stream_settle seconds (or until the cursor ▍
        disappears).  Robust against dynamic re-renders that can invalidate
        previous WebElement handles.
        """
        last_snapshot = ""
        stable_since = time.monotonic()

        while True:
            try:
                blocks = self._assistant_blocks()[start_index:]
                # Build the combined text in one go; if any element goes stale
                # we’ll jump to except and retry on the next poll.
                joined = "\n".join(blk.text for blk in blocks)
            except StaleElementReferenceException:
                time.sleep(self.cfg.poll_interval / 2)
                continue  # re-try the loop on the next tick

            has_cursor = joined.endswith("▍")

            if joined == last_snapshot and not has_cursor:
                if time.monotonic() - stable_since >= self.cfg.stream_settle:
                    break
            else:
                last_snapshot = joined
                stable_since = time.monotonic()

            time.sleep(self.cfg.poll_interval)

    # 4-D.  Tiny wrappers around Selenium
    # -----------------------------------

    def _assistant_blocks(self):
        return self.driver.find_elements(By.XPATH, Locators.ASSISTANT_BLOCK_XPATH)

    def _wait_visible(self, by: By, locator: str):
        return self.wait.until(EC.visibility_of_element_located((by, locator)))

    def _click(self, by: By, locator: str) -> None:
        self.wait.until(EC.element_to_be_clickable((by, locator))).click()

    def _human_type(self, element, text: str) -> None:
        lo, hi = self.cfg.key_delay_range
        for ch in text:
            element.send_keys(ch)
            time.sleep(random.uniform(lo, hi))


# ──────────────────────────────────────────────────────────────
# 5.  Tiny CLI for manual testing
# ──────────────────────────────────────────────────────────────

def main() -> None:
    try:
        with ChatGPTWebAutomator() as bot:
            print("🤖  ChatGPT browser ready (Ctrl-C to quit)\n")
            while True:
                prompt = input("You : ")
                bot.open_new_chat(model="o3")        # manual test
                for chunk in bot.send_message(prompt):
                    print(f"Bot : {chunk}\n")
    except KeyboardInterrupt:
        print("\n✋  Session ended.")


if __name__ == "__main__":
    main()