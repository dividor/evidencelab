"""
LangSmith utility for tracing LLM calls.

This module ensures LangSmith environment variables are properly configured
for tracing all LLM calls made through LangChain.
"""

import os


def setup_langsmith_tracing():
    """
    Setup LangSmith tracing by mapping LANGSMITH_* vars to LANGCHAIN_* vars.

    LangChain looks for LANGCHAIN_* variables, but users might set LANGSMITH_*.
    This function ensures both naming conventions work.
    """
    # Map LANGSMITH_API_KEY to LANGCHAIN_API_KEY
    if os.getenv("LANGSMITH_API_KEY") and not os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY")

    # Map LANGSMITH_PROJECT to LANGCHAIN_PROJECT
    if os.getenv("LANGSMITH_PROJECT") and not os.getenv("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT")

    # Ensure tracing is enabled if API key is present
    if os.getenv("LANGCHAIN_API_KEY") and not os.getenv("LANGCHAIN_TRACING_V2"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"


# Auto-setup on import
setup_langsmith_tracing()
