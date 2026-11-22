import logging

from app.logging_setup import RedactingFilter


def test_redacts_secrets_and_gemini_key_pattern():
    f = RedactingFilter(["s3cr3t-pass"])
    rec = logging.LogRecord("x", logging.INFO, "", 0, "senha=%s chave=%s", ("s3cr3t-pass", "AIza" + "A" * 30), None)
    assert f.filter(rec)
    assert "s3cr3t-pass" not in rec.msg and "AIza" not in rec.msg
    assert rec.msg == "senha=*** chave=***"
