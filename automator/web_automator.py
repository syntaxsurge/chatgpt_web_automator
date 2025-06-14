from __future__ import annotations

import logging
import random
import shutil
import time
from typing import Optional

import pyperclip
import undetected_chromedriver as uc
from fake_useragent import UserAgent
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import ENABLE_DEBUG
from .locators import Locators
from .models import ClientConfig, Credentials

_logger = logging.getLogger(__name__)
if ENABLE_DEBUG and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")


class ChatGPTWebAutomator:
    """
    Streamlined wrapper around ChatGPT’s web UI that *only* submits prompts and
    returns the resulting conversation ID without waiting for the assistant.
    """

    HOME_URL = "https://chatgpt.com/"

    # —— life‑cycle ————————————————————————————————————————————

    def __init__(
            self,
            config: Optional[ClientConfig] = None,
            creds: Optional[Credentials] = None,
    ) -> None:
        self.cfg = config or ClientConfig()
        self.creds = creds or Credentials()
        self.driver = self._launch_driver()
        self.wait = WebDriverWait(self.driver, self.cfg.explicit_timeout)

        self.driver.get(self.HOME_URL)
        if self.cfg.auto_login:
            self._perform_login()

    # —— public API —————————————————————————————————————————

    def open_new_chat(self, model: Optional[str] = None) -> None:
        url = self.HOME_URL if not model else f"{self.HOME_URL}?model={model}"
        self.driver.get(url)
        self._wait_visible(By.ID, Locators.PROMPT_TEXTAREA_ID)

    def send_prompt(self, prompt: str) -> str:
        """
        Submit *prompt* and return the newly assigned conversation ID.

        The method waits up to 10 s for the URL to switch from */?model=…* to
        */c/<chat_id>* then extracts and returns ``<chat_id>``.
        """
        textarea = self._wait_visible(By.ID, Locators.PROMPT_TEXTAREA_ID)
        self._human_type(textarea, prompt)
        self._click(By.ID, Locators.SUBMIT_BUTTON_ID)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            current = self.driver.current_url
            if "/c/" in current:
                chat_id = (
                    current.split("/c/")[1]
                    .split("?")[0]
                    .rstrip("/")
                    .strip()
                )
                if chat_id:
                    return chat_id
            time.sleep(0.1)

        raise RuntimeError("Conversation ID not detected within 10 s")

    def quit(self) -> None:
        """Terminate Chrome and delete any temporary profile."""
        try:
            self.driver.quit()
        finally:
            if self.cfg.profile_dir.exists() and "chatgpt_profile_" in str(self.cfg.profile_dir):
                shutil.rmtree(self.cfg.profile_dir, ignore_errors=True)

    # —— context manager support ——————————————————————————

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.quit()

    # —— private helpers ————————————————————————————————

    def _launch_driver(self) -> Chrome:
        ua = UserAgent().random
        profile = self.cfg.profile_dir
        profile.mkdir(parents=True, exist_ok=True)

        opts = ChromeOptions()
        opts.add_argument(f"--user-agent={ua}")
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

    # —— optional login ————————————————————————————————

    def _perform_login(self) -> None:
        email = self._wait_visible(By.ID, Locators.EMAIL_INPUT_ID)
        self._human_type(email, self.creds.email)
        self._click(By.XPATH, Locators.EMAIL_CONTINUE_XPATH)

        pwd = self._wait_visible(By.ID, Locators.PASSWORD_INPUT_ID)
        self._human_type(pwd, self.creds.password)
        self._click(By.XPATH, Locators.PASSWORD_CONTINUE_XPATH)

    # —— selenium wrappers ————————————————————————————

    def _wait_visible(self, by: By | str, locator: str):
        return self.wait.until(EC.visibility_of_element_located((str(by), locator)))

    def _click(self, by: By | str, locator: str) -> None:
        self.wait.until(EC.element_to_be_clickable((str(by), locator))).click()

    # —— input helpers ——————————————————————————————

    def _human_type(self, element, text: str) -> None:
        """
        Type *text* into *element* using configured typing mode.
        """
        mode = self.cfg.typing_mode

        if mode == "paste":
            ctrl = self.cfg.ctrl_or_cmd()
            element.click()
            element.send_keys(ctrl, "a")
            element.send_keys(Keys.DELETE)
            pyperclip.copy(text)
            ActionChains(self.driver).key_down(ctrl).send_keys("v").key_up(ctrl).perform()
            return

        if mode == "fast":
            element.send_keys(text)
            return

        lo, hi = self.cfg.key_delay_range
        for ch in text:
            if ch == "\n":
                element.send_keys(Keys.SHIFT, Keys.ENTER)
            else:
                element.send_keys(ch)
            time.sleep(random.uniform(lo, hi))
