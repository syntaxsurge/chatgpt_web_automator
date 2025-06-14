from __future__ import annotations

import sys

from utils.chat_backend import ChatBackendClient

# Hard-coded conversation ID for smoke testing
CONVERSATION_ID: str = "684d209e-16ac-8003-a960-3a85e664d07f"


def main() -> None:
    client = ChatBackendClient()
    try:
        reply = client.wait_for_completion(
            CONVERSATION_ID,
            timeout_seconds=900.0,
            poll_interval=1.0,
        )
        print(reply)
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
