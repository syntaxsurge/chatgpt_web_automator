class Locators:
    # Login page
    EMAIL_INPUT_ID = ":r1:-email"
    PASSWORD_INPUT_ID = ":re:-password"
    EMAIL_CONTINUE_XPATH = "//*[@id=':r1:']/div[2]/button"
    PASSWORD_CONTINUE_XPATH = "//*[@id=':re:']/div[2]/button"

    # Chat UI
    PROMPT_TEXTAREA_ID = "prompt-textarea"
    SUBMIT_BUTTON_ID = "composer-submit-button"

    # Streaming controls
    STOP_BUTTON_SELECTOR = "button[data-testid='stop-button']"
    SEND_BUTTON_SELECTOR = "button[data-testid='send-button']"

    # Assistant messages only (excludes user bubbles)
    ASSISTANT_BLOCK_XPATH = (
        "//div[@data-message-author-role='assistant']//div[contains(@class,'prose')]"
    )

    # Error bubbles rendered by ChatGPT (network / length / generic)
    # Error bubbles (e.g. "network error”, "message too long”) are rendered as
    # a coloured div with retry button.  Detect either the classic error class
    # combination *or* any div that contains the retry button data-test id.
    ERROR_BLOCK_XPATH = (
        "("
        "//div[contains(@class,'text-token-text-error') "
        "and contains(@class,'border-token-surface-error')]"
        ")"
        " | "
        "("
        "//div[descendant::button[@data-testid='regenerate-thread-error-button']]"
        ")"
        " | "
        "("
        "//p[normalize-space(.)='The message you submitted was too long, please reload the conversation and submit something shorter.']"
        ")"
    )