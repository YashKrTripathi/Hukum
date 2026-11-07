"""Removes secrets and personal numbers from text before it is stored, logged or sent to a model."""
import re

_RULES = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[private key]"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{16,}"), "[api key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[github token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}"), "[aws key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), "[jwt]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{16,}"), "bearer [token]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_ -]?key|token)\b\s*[:=]\s*\S+"), r"\1=[hidden]"),
    (re.compile(r"(?i)\b(otp|one[- ]time (?:password|code)|verification code|code is)\b[^0-9\n]{0,20}\d{4,8}"), "[otp hidden]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card number]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[id number]"),
]


def redact(text):
    s = str(text or "")
    for rx, rep in _RULES:
        s = rx.sub(rep, s)
    return s
