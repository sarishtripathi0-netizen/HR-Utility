"""Normalising names, cadres, mobiles, dates and place names from messy source cells."""
from __future__ import annotations

import difflib
import re
from datetime import date, datetime

_HONORIFIC = re.compile(r"^\s*(shri|sri|smti|smt|ms|mr|mrs|miss)\b\.?\s*", re.I)
_DR = re.compile(r"^\s*dr\b\.?\s*", re.I)
_CADRE = re.compile(r"[,\s]*\b(IAS|ACS|ALRS|ALSR)\b\.?", re.I)
_TRAINEE = re.compile(r"\(\s*trainee officer\s*\)", re.I)


def split_cadre(raw) -> tuple[str, str | None]:
    """'Sri Aayush Garg,IAS' -> ('Aayush Garg', 'IAS'). Keeps 'Dr.' in the display name."""
    s = str(raw).replace("\n", " ").strip()
    s = _TRAINEE.sub("", s)
    found = _CADRE.findall(s)
    cadre = found[-1].upper().replace("ALSR", "ALRS") if found else None
    s = _CADRE.sub("", s)
    prev = None
    while prev != s:
        prev = s
        s = _HONORIFIC.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    if s.isupper():
        s = s.title()
    return s, cadre


def name_key(name: str) -> str:
    s = name.lower()
    prev = None
    while prev != s:
        prev = s
        s = _DR.sub("", _HONORIFIC.sub("", s))
    s = re.sub(r"\bkr\b\.?", "kumar", s)
    return re.sub(r"[^a-z]", "", s)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def mobiles(raw) -> list[str]:
    """Every phone number in a cell, as 10 digits where possible."""
    if raw is None:
        return []
    if isinstance(raw, float):
        raw = int(raw)
    out = []
    for token in re.findall(r"\d[\d\- ]{6,}\d", str(raw)):
        digits = re.sub(r"\D", "", token)
        if len(digits) >= 20 and len(digits) % 10 == 0:
            out.extend(digits[i:i + 10] for i in range(0, len(digits), 10))
            continue
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        out.append(digits)
    return out


def email_of(raw) -> str | None:
    if raw is None:
        return None
    m = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", str(raw).replace(" ", ""))
    return m.group(0).lower() if m else None


def iso_date(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", str(raw))
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    try:
        return date(y, mth, d).isoformat()
    except ValueError:
        return None


def batch_year(raw) -> int | None:
    """'DR-2019' -> 2019, 'DR-92' -> 1992, '(RR-2024)' -> 2024, 'SCS-2011' -> 2011."""
    if raw is None:
        return None
    m = re.search(r"(\d{4}|\d{2})\b", str(raw))
    if not m:
        return None
    y = int(m.group(1))
    if y < 100:
        y += 1900 if y > 30 else 2000
    return y


def norm_place(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())


def clean_unit(raw) -> str:
    """'South Salmara (Pt) Revenue Circle ' -> 'South Salmara (Pt)'."""
    s = str(raw).replace("\n", " ")
    s = re.sub(r"(?i)o/o\s+circle officer,?", "", s)
    s = re.sub(r"(?i),?\s*revenue circle office", "", s)
    s = re.sub(r"(?i)\brev(enue)?\.?\s*circle\b.*$", "", s)
    s = re.sub(r"(?i)\bcircle\b", "", s)
    s = re.sub(r"(?i)\brco\b", "", s)
    return re.sub(r"\s+", " ", s).strip(" ,.")


def post_from_text(text: str) -> tuple[str | None, str | None]:
    """Map a designation string to a post code. Returns (post_code, reason_if_unmapped)."""
    t = re.sub(r"\s+", " ", str(text).lower())
    if re.search(r"assistant\.? district commissioner", t):
        return None, "Assistant District Commissioner (IAS trainee) is not in the post code list"
    if "district development commissioner" in t:
        return None, "District Development Commissioner is not in the post code list"
    if re.search(r"co-? ?district commissioner", t):
        return "CDC", None
    if re.search(r"\b(addl\.?|additional) ?district commissioner|\badc\b", t):
        return "ADC", None
    if "assistant commissioner" in t:
        return "AC", None
    if "circle officer" in t:
        return "CO", None
    if "district commissioner" in t:
        return "DC", None
    if "election officer" in t:
        return None, "'Election Officer' is not a post code; post taken from the gradation list if found"
    return None, f"no post code for designation '{text.strip()[:60]}'"
