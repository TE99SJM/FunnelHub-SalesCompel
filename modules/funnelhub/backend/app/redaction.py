"""Remove loaded credentials from provider diagnostics before storage/logging."""
import logging
import re
import threading
from urllib.parse import quote, quote_plus

_values = set()
_lock = threading.Lock()


def protect(value):
    if isinstance(value, dict):
        for v in value.values(): protect(v)
    elif isinstance(value, (list, tuple)):
        for v in value: protect(v)
    elif isinstance(value, str) and len(value) >= 8:
        with _lock:
            _values.update((value, quote(value, safe=""), quote_plus(value)))
    return value


def redact(value):
    text = str(value)
    with _lock:
        values = sorted(_values, key=len, reverse=True)
    for secret in values:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:access_token|refresh_token|client_secret|app_password|api_key|password|key)=)[^&\s]+", r"\1[REDACTED]", text)
    return text


class SecretFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
            record.exc_text = None
        record.msg, record.args = redact(message), ()
        return True
