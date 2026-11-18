"""Readers for each source file. Each returns Sightings: one person seen once, in one source."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from .names import (
    batch_year,
    clean_unit,
    email_of,
    iso_date,
    mobiles,
    norm_place,
    post_from_text,
    split_cadre,
)

# Source priority: lower wins when sources disagree about where a person sits.
P_DC_LIST = 1      # List_of_DCs.xlsx — "the updated list to rely on"
P_ALLOTMENT = 2    # Nagaon work-allotment order, 13-03-2026
P_GRADATION = 3    # IAS / ACS gradation lists, August 2026


@dataclass
class District:
    code: str
    name: str
    abbr: str
    aliases: list[str]
    mdm_code: str = ""


@dataclass
class Sighting:
    source: str
    ref: str
    priority: int
    name: str
    cadre: str | None
    post_code: str | None = None
    office_type: str | None = None
    district_code: str | None = None
    unit: str | None = None            # district name for DC offices, unit name otherwise
    placement: bool = False            # proposes a posting (vs. enrichment only)
    mobiles: list[str] = field(default_factory=list)
    email: str | None = None
    year: int | None = None
    dob: str | None = None
    dor: str | None = None
    joined: str | None = None          # source's "date of joining post", kept as a note
    raw_designation: str | None = None
    unmapped_reason: str | None = None
    functions_text: list[str] = field(default_factory=list)
    order: int = 0


def load_districts(config_dir: Path) -> list[District]:
    with open(config_dir / "districts.csv", newline="", encoding="utf-8") as f:
        return [District(r["district_code"], r["name"], r["abbr"], r["aliases"].split("|"), r.get("mdm_district_code") or "")
                for r in csv.DictReader(f)]


CITY_ALIASES = {"guwahati"}  # only trusted in a District/HQ column, not inside posting text


def district_exact(text, districts: list[District]) -> District | None:
    n = norm_place(text or "")
    return next((d for d in districts if n and n in d.aliases), None)


def district_in(text, districts: list[District], allow_city: bool = False) -> District | None:
    n = norm_place(text or "")
    for d in districts:
        for a in d.aliases:
            if a in CITY_ALIASES and not allow_city:
                continue
            if a and a in n:
                return d
    return None


def _cells(row) -> list:
    return [c for c in row]


def _s(v) -> str:
    return "" if v is None else str(v).strip()


# ---------------------------------------------------------------- List_of_DCs.xlsx

def parse_dc_list(path: Path, districts: list[District], ignored: dict) -> list[Sighting]:
    wb = openpyxl.load_workbook(path, data_only=True)
    out: list[Sighting] = []
    src = path.name

    ws = wb["DC"]
    for i, row in enumerate(ws.iter_rows(min_row=3, values_only=True), start=3):
        vals = [v for v in row if v is not None and _s(v)]
        texts = [_s(v) for v in vals]
        dist = None
        idx = None
        for k, t in enumerate(texts):
            d = district_exact(t, districts)
            if d:
                dist, idx = d, k
                break
        if not dist:
            continue
        rest = [t for t in texts[idx + 1:] if not district_exact(t, districts)]
        if not rest:
            continue
        name, cadre = split_cadre(rest[0])
        out.append(Sighting(src, f"DC!row{i}", P_DC_LIST, name, cadre, "DC", "DC_OFFICE", dist.code, dist.name,
                            True, mobiles(" \n".join(rest[1:]))))

    ws = wb["CDC"]
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        dist = district_exact(_s(row[1]) if len(row) > 1 else "", districts)
        if not dist or not _s(row[2]):
            continue
        lines = [ln.strip() for ln in _s(row[2]).split("\n") if ln.strip()]
        phones = [ln.strip() for ln in _s(row[3] if len(row) > 3 else "").split("\n") if ln.strip()]
        for j, ln in enumerate(lines):
            m = re.match(r"^(.*?)\s*\(([^)]*)\)?\s*$", ln)
            raw_name, unit = (m.group(1), m.group(2).strip()) if m else (ln, None)
            name, cadre = split_cadre(raw_name)
            out.append(Sighting(src, f"CDC!row{i}.{j + 1}", P_DC_LIST, name, cadre, "CDC", "CO_DISTRICT_OFFICE",
                                dist.code, unit, True, mobiles(phones[j]) if j < len(phones) else []))

    ws = wb["ADC "]
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        dist = district_exact(_s(row[1]) if len(row) > 1 else "", districts)
        if not dist:
            continue
        for k in (2, 4):
            if len(row) > k and _s(row[k]):
                name, cadre = split_cadre(row[k])
                out.append(Sighting(src, f"ADC!row{i}", P_DC_LIST, name, cadre, "ADC", "DC_OFFICE", dist.code,
                                    dist.name, True, mobiles(row[k + 1] if len(row) > k + 1 else None)))

    ws = wb["COs "]
    current: District | None = None
    in_poc_block = False
    extra_cols = 0
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        a, b, c, d, e, f = (row[k] if len(row) > k else None for k in range(6))
        if any(_s(row[k]) for k in range(6, min(len(row), 9))):
            extra_cols += 1
        is_header = not _s(c) and not _s(d) and not _s(e) and not _s(f) and (_s(a) or _s(b)) and not str(a or "").strip().isdigit()
        if is_header and not isinstance(a, (int, float)):
            current = district_exact(_s(a) or _s(b), districts)
            in_poc_block = current is not None
            continue
        if not in_poc_block or not _s(b):
            continue
        names = [x.strip() for x in _s(b).split("\n") if x.strip()]
        desigs = [x.strip() for x in _s(e).split("\n") if x.strip()]
        emails = [x.strip() for x in _s(c).split("\n") if x.strip()]
        phones = [x.strip() for x in _s(d).split("\n") if x.strip()]
        for j, raw in enumerate(names):
            desig = desigs[j] if j < len(desigs) else (desigs[0] if desigs else "")
            post, why = post_from_text(desig) if desig else (None, "no designation")
            if re.fullmatch(r"(?i)co\s*\(a\)", desig.strip()):
                post, why = "CO", None
            name, cadre = split_cadre(raw)
            sighting = Sighting(src, f"COs!row{i}.{j + 1}", P_DC_LIST, name, cadre, post,
                                "CIRCLE_OFFICE" if post == "CO" else None, current.code, clean_unit(f),
                                post == "CO", mobiles(phones[j]) if j < len(phones) else [],
                                email_of(emails[j]) if j < len(emails) else None, raw_designation=desig,
                                unmapped_reason=why)
            out.append(sighting)
    ignored["co_sheet_rows_with_unlabelled_columns_G_to_I"] = extra_cols
    return out


# ---------------------------------------------------------------- Gradation lists

def _gradation_office(post: str, text: str, district: District) -> tuple[str, str]:
    if post == "AC":
        m = re.search(r"([A-Za-z]+)\s+co-?district", text, re.I)
        if m:
            return "CO_DISTRICT_OFFICE", m.group(1).title()
    return "DC_OFFICE", district.name


def parse_acs_gradation(path: Path, districts: list[District]) -> list[Sighting]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    out = []
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not r or not _s(r[1]):
            continue
        name, cadre = split_cadre(r[1])
        posting = _s(r[3])
        post, why = post_from_text(posting)
        dist = district_in(posting, districts) or district_in(_s(r[8]), districts, allow_city=True)
        s = Sighting(path.name, f"row{i}", P_GRADATION, name, cadre or "ACS", post, None,
                     dist.code if dist else None, None, False, mobiles(r[13]), email_of(r[28] if len(r) > 28 else None),
                     batch_year(r[2]), iso_date(r[14]), iso_date(r[25] if len(r) > 25 else None),
                     joined=_s(r[9]) or None, raw_designation=posting, unmapped_reason=why)
        if post in ("ADC", "AC") and dist and district_in(posting, districts):
            s.office_type, s.unit = _gradation_office(post, posting, dist)
            s.placement = True
        elif post in ("DC", "CDC") and dist:
            s.office_type = "DC_OFFICE" if post == "DC" else "CO_DISTRICT_OFFICE"
            s.unit = dist.name if post == "DC" else _cdc_unit(posting)
        out.append(s)
    return out


def _cdc_unit(posting: str) -> str | None:
    m = re.search(r"co-?\s?district commissioner,?\s*([A-Za-z .]+?)(,|\.|$)", posting, re.I)
    return m.group(1).strip().title() if m else None


def parse_ias_gradation(path: Path, districts: list[District]) -> list[Sighting]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    out = []
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not r or not _s(r[1]):
            continue
        name, cadre = split_cadre(r[1])
        posting = _s(r[4])
        post, why = post_from_text(posting)
        dist = district_in(posting, districts) or district_in(_s(r[11]), districts, allow_city=True)
        s = Sighting(path.name, f"row{i}", P_GRADATION, name, cadre or "IAS", post, None,
                     dist.code if dist else None, None, False, mobiles(r[15] if len(r) > 15 else None),
                     email_of(r[8]), batch_year(r[2]), iso_date(r[17] if len(r) > 17 else None),
                     iso_date(r[18] if len(r) > 18 else None), joined=_s(r[6]) or None,
                     raw_designation=posting, unmapped_reason=why)
        if post in ("ADC", "AC") and dist and district_in(posting, districts):
            s.office_type, s.unit = _gradation_office(post, posting, dist)
            s.placement = True
        elif post in ("DC", "CDC") and dist:
            s.office_type = "DC_OFFICE" if post == "DC" else "CO_DISTRICT_OFFICE"
            s.unit = dist.name if post == "DC" else _cdc_unit(posting)
        out.append(s)
    return out


# ---------------------------------------------------------------- Nagaon work allotment (PDF)

def parse_nagaon_allotment(path: Path, districts: list[District]) -> list[Sighting]:
    import pdfplumber

    nagaon = next(d for d in districts if d.code == "26")
    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if row and _s(row[0]).lower().startswith("sl"):
                        continue
                    rows.append([_s(c) for c in row])
    officers: list[list[str]] = []
    for row in rows:
        if len(row) < 3:
            continue
        if not row[0] and not row[1] and officers:
            officers[-1][2] += "\n" + row[2]
        else:
            officers.append(row)
    out = []
    for sl, who, works in officers:
        lines = [ln.strip() for ln in who.split("\n") if ln.strip()]
        name, cadre = split_cadre(lines[0])
        rest = " ".join(lines[1:])
        phone = re.search(r"Ph\.?\s*([\d ]+)", rest)
        designation = re.sub(r"Ph\.?\s*[\d ]+", "", rest).strip(" ,")
        post, why = post_from_text(designation)
        items: list[str] = []
        for ln in works.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            m = re.match(r"^\d+\.\s*(.*)$", ln)
            if m or not items:
                items.append(m.group(1) if m else ln)
            else:
                items[-1] += " " + ln
        s = Sighting(path.name, f"Sl {sl}", P_ALLOTMENT, name, cadre, post, None, nagaon.code, None, False,
                     mobiles(phone.group(1)) if phone else [], raw_designation=designation, unmapped_reason=why,
                     functions_text=items)
        if post in ("ADC", "AC"):
            s.office_type, s.unit, s.placement = "DC_OFFICE", nagaon.name, True
        elif post == "CDC":
            m = re.search(r"co-?district commissioner,?\s*([A-Za-z]+)", designation, re.I)
            s.office_type, s.unit, s.placement = "CO_DISTRICT_OFFICE", m.group(1).title() if m else None, True
        out.append(s)
    return out


# ---------------------------------------------------------------- PoC master data workbook (reference only)

@dataclass
class GeoCircle:
    circle_code: str
    circle_name: str
    geo_district_code: str
    district_code: str  # numeric code from config/districts.csv


@dataclass
class PocMasterData:
    circles: list[GeoCircle]
    geo_district_codes: dict[str, str]      # numeric district code -> Geo Master code (e.g. 27 -> NLB)
    dept_names: dict[str, str]              # dept code -> final department name (Service ID Blocks)
    official_depts: list[str]
    officer_rows: int                       # Officer Directory rows (synthetic; never imported)


def parse_poc_master(path: Path, districts: list[District]) -> PocMasterData:
    """Reads only reference data. The Officer Directory is synthetic and the role sheets belong to the
    Rule Engine; neither is imported."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    circles, geo_codes = [], {}
    for r in wb["Geo Master"].iter_rows(min_row=2, values_only=True):
        code, name, gcode, gname = (r[4], r[5], r[6], r[7]) if len(r) > 7 else (None,) * 4
        d = district_exact(gname, districts) if gname else None
        if d and code and name:
            circles.append(GeoCircle(_s(code), _s(name), _s(gcode), d.code))
            geo_codes[d.code] = _s(gcode)
    dept_names = {}
    rows = wb["Service ID Blocks"].iter_rows(values_only=True)
    header = [_s(h) for h in next(rows)]
    code_col, final_col = header.index("Dept Code"), header.index("Dept Full Name (final)")
    for r in rows:
        if r and len(r) > final_col and _s(r[code_col]) and _s(r[final_col]):
            dept_names[_s(r[code_col])] = _s(r[final_col])
    official = [_s(r[1]) for r in wb["Official Dept List"].iter_rows(min_row=2, values_only=True) if r and len(r) > 1 and _s(r[1])]
    officer_rows = sum(1 for r in wb["Officer Directory"].iter_rows(min_row=2, values_only=True) if r and r[0])
    return PocMasterData(circles, geo_codes, dept_names, official, officer_rows)


# ---------------------------------------------------------------- Earlier PoC (cross-check only)

@dataclass
class LinkedOfficer:
    officer_id: str
    office_id: str
    name: str
    cadre: str
    post_text: str
    district: str
    office_name: str


def parse_linked_masters(path: Path) -> list[LinkedOfficer]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    offices = {}
    for r in wb["5 Office Master"].iter_rows(min_row=5, values_only=True):
        if r and _s(r[0]).startswith("OFF-"):
            offices[_s(r[0])] = _s(r[2])
    out = []
    for r in wb["7 Officer Master"].iter_rows(min_row=5, values_only=True):
        if r and _s(r[0]) and _s(r[1]).startswith("OFF-"):
            name, _ = split_cadre(r[2])
            out.append(LinkedOfficer(_s(r[0]), _s(r[1]), name, _s(r[3]), _s(r[4]), _s(r[5]), offices.get(_s(r[1]), "")))
    return out
