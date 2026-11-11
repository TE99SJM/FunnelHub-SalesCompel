import logging

from app.redaction import SecretFilter, protect, redact


def test_credentials_are_redacted_in_text_urls_and_logging():
    protect({"token":"fixture-secret/token+value"})
    assert "fixture-secret" not in redact("error fixture-secret/token+value")
    assert "fixture-secret" not in redact("error fixture-secret%2Ftoken%2Bvalue")
    assert "abc" not in redact("Bearer abc123")
    assert "secret123" not in redact("https://example.invalid/?access_token=secret123&ok=1")
    record = logging.LogRecord("oneshot",logging.WARNING,"test",1,"Failed %s",("fixture-secret/token+value",),None)
    assert SecretFilter().filter(record)
    assert "fixture-secret" not in record.getMessage()
