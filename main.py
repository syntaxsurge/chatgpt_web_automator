from __future__ import annotations

import logging

from config import ENABLE_DEBUG
from automator.web_automator import ChatGPTWebAutomator

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

_logger = logging.getLogger(__name__)
if ENABLE_DEBUG and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")


# ──────────────────────────────────────────────────────────────
# Simple CLI for manual testing
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