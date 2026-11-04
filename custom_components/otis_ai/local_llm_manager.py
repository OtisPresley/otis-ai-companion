"""Otis AI Companion: Local LLM Manager module alias and re-exports.

Maintains module naming parity with roadmap specifications.
"""
from __future__ import annotations

from .local_llm import *  # noqa: F401, F403
from .local_llm import (
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_LOCAL_LLM_URL,
    DEFAULT_LOCAL_VISION_MODEL,
    DEFAULT_OTIS_TOOLS,
    DEFAULT_TIMEOUT_SECONDS,
    LocalLLMManager,
    extract_tool_calls,
    normalize_image_base64,
    validate_tool_call,
)

__all__ = [
    "DEFAULT_LOCAL_LLM_MODEL",
    "DEFAULT_LOCAL_LLM_URL",
    "DEFAULT_LOCAL_VISION_MODEL",
    "DEFAULT_OTIS_TOOLS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LocalLLMManager",
    "extract_tool_calls",
    "normalize_image_base64",
    "validate_tool_call",
]
