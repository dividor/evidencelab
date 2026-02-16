import os

from slowapi import Limiter
from slowapi.util import get_remote_address


def get_rate_limits() -> tuple[str, str, str]:
    rate_limit_search = os.environ.get("RATE_LIMIT_SEARCH", "30/minute")
    rate_limit_default = os.environ.get("RATE_LIMIT_DEFAULT", "60/minute")
    rate_limit_ai = os.environ.get("RATE_LIMIT_AI", "10/minute")
    return rate_limit_search, rate_limit_default, rate_limit_ai


def get_rate_limit_translate() -> str:
    return os.environ.get("RATE_LIMIT_TRANSLATE", "60/minute")


limiter = Limiter(key_func=get_remote_address)
