"""
Automator package exposing the high-level ChatGPTWebAutomator together with its
configuration data classes.
"""
from .web_automator import ChatGPTWebAutomator
from .models import ClientConfig, Credentials

__all__ = ["ChatGPTWebAutomator", "ClientConfig", "Credentials"]