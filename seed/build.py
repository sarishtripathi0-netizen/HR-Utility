"""Build the seed: ./data sources -> data/mdm_seed/*.csv, data/hr_seed/*.csv, data/load_report.md.

Run:  python -m seed.build

The builder plays MDM for the PoC: it derives offices and chairs, and mints EMP- IDs for every
person it finds. Every judgement call it makes is written to load_report.md.
"""
from __future__ import annotations

import csv
import difflib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from hr_utility.mdm.mapping import SNAPSHOT_TYPES, load_mdm_config, office_unit_name, snapshot_records

from .names import name_key, norm_place, similarity
from .parsers import (
    P_ALLOTMENT,
    P_DC_LIST,
    P_GRADATION,
    District,
    Sighting,
    load_districts,
    parse_acs_gradation,
    parse_dc_list,
    parse_ias_gradation,
    parse_linked_masters,
    parse_nagaon_allotment,
    parse_poc_master,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"

SOURCES = {
    "mdm_reference": "Sewa_Setu_MDM_Reference.xlsx",
    "dc_list": "List_of_DCs.xlsx",
    "ias": "IAS_Gradation_List_Aug_2026.xlsx",
    "acs": "ACS_Gradation_List_Aug_2026.xlsx",
    "allotment": "Officers_Workallotment_13_03_26.pdf",
    "linked": "Sewa_Setu_PoC_Linked_Masters.xlsx",
    "poc_master": "PoC_master_data.xlsx",
}
OPTIONAL_SOURCES = {"poc_master"}
OFFICE_PREFIX = {"DC_OFFICE": "DCO", "CO_DISTRICT_OFFICE": "CDO", "CIRCLE_OFFICE": "RCO"}


def place_score(a: str, b: str) -> float:
    """How alike two place names are: 1.0 equal, 0.95 one contains the other, else a similarity ratio."""
    a, b = norm_place(a), norm_place(b)
    if a == b:
        return 1.0
    if a and b and (a in b or b in a):
        return 0.95
    return similarity(a, b)


def greedy_pairs(scores: list[tuple[float, int, int]], threshold: float = 0.75) -> list[tuple[float, int, int]]:
    """Best-first one-to-one matching."""
    used_a, used_b, out = set(), set(), []
    for sc, i, j in sorted(scores, reverse=True):
        if sc >= threshold and i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            out.append((sc, i, j))
    return out
OFFICE_NAME = {
    "DC_OFFICE": "Office of the District Commissioner, {}",
    "CO_DISTRICT_OFFICE": "Co-District Office, {}",
    "CIRCLE_OFFICE": "Revenue Circle Office, {}",
}


@dataclass
class Person:
    key: str
    name: str
    cadre: str | None = None
    sightings: list[Sighting] = field(default_factory=list)
    mobiles: set[str] = field(default_factory=set)
    districts: set[str] = field(default_factory=set)
    year: int | None = None
    dob: str | None = None
    dor: str | None = None
    email: str | None = None
    is_demo: bool = False
    employee_id: str | None = None
    note: str | None = None

    def placements(self) -> list[Sighting]:
        return [s for s in self.sightings if s.placement]


@dataclass
class Chair:
    office_key: tuple
    post_code: str
    holder: Person
    source: str
    is_demo: bool = False


class Report:
    def __init__(self):
        self.sections: dict[str, list[str]] = defaultdict(list)

    def add(self, section: str, line: str) -> None:
        if line not in self.sections[section]:
            self.sections[section].append(line)


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if not next(iter(r.values()), "").startswith("#")]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def seniority(p: Person) -> tuple:
    return (p.year is None, p.year or 0, p.name.lower())


class Builder:
    def __init__(self, data_dir: Path):
        self.data = Path(data_dir)
        self.cfg_dir = self.data / "config"
        self.cfg = json.loads((self.cfg_dir / "seed.json").read_text(encoding="utf-8"))
        self.threshold = float(self.cfg["fuzzy_name_threshold"])
        self.districts: list[District] = load_districts(self.cfg_dir)
        self.dist_by_code = {d.code: d for d in self.districts}
        self.posts = {r["post_code"]: r for r in _read_csv(self.cfg_dir / "posts.csv")}
        self.rank = {k: int(v["rank_order"]) for k, v in self.posts.items()}
        self.issuing = {r["cadre"]: r["issuing_department"] for r in _read_csv(self.cfg_dir / "issuing_departments.csv")}
        self.function_codes = _read_csv(self.cfg_dir / "function_codes.csv")
        self.branch_map = [(re.compile(r["pattern"], re.I), r["function_code"]) for r in _read_csv(self.cfg_dir / "nagaon_branch_map.csv")]
        self.post_rules = {r["post_code"]: r for r in _read_csv(self.cfg_dir / "post_function_rules.csv")}
        self.catalogue = self._expand_catalogue(_read_csv(self.cfg_dir / "office_type_functions.csv"))
        self.bundles: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in _read_csv(self.cfg_dir / "demo_function_bundles.csv"):
            fns = r["functions"].split("|")
            bad = [f for f in fns if f not in self.catalogue.get(r["office_type"], {})]
            if bad:
                raise ValueError(f"demo_function_bundles.csv: {bad} are not on the {r['office_type']} function list")
            self.bundles[(r["office_type"], r["post_code"])].append({**r, "functions": fns})
        self.report = Report()
        self.ignored: dict = {}
        self.persons: list[Person] = []
        self.used_office_ids: set[str] = set()
        self.poc = None
        self.mdm_cfg = load_mdm_config(self.data)
        self.mdm = self._load_mdm_snapshot()
        self.key_index: dict[str, list[Person]] = {}
        self.holder_index: dict[int, Person] = {}
        self.order = 0

    def _load_mdm_snapshot(self) -> dict | None:
        """data/mdm_snapshot/*.json, saved by `python -m seed.mdm_pull` from the MDM PoC."""
        snap_dir = self.data / "mdm_snapshot"
        if not (snap_dir / "office.json").exists():
            return None
        out = {"version": json.loads((snap_dir / "version.json").read_text(encoding="utf-8"))
               if (snap_dir / "version.json").exists() else {}}
        for t in SNAPSHOT_TYPES:
            p = snap_dir / f"{t}.json"
            out[t] = snapshot_records(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else []
        return out

    def _expand_catalogue(self, rows: list[dict]) -> dict[str, dict[str, dict]]:
        """office_type -> {function_code: row}. 'category:X' expands to every code of that category."""
        codes = {f["code"]: f for f in self.function_codes}
        out: dict[str, dict[str, dict]] = {}
        for r in rows:
            entry = out.setdefault(r["office_type"], {})
            for token in r["functions"].split("|"):
                token = token.strip()
                found = [c for c, f in codes.items() if f["category"] == token[9:]] if token.startswith("category:") else [token]
                for code in found:
                    if code not in codes:
                        raise ValueError(f"office_type_functions.csv: {code} is not in function_codes.csv")
                    entry[code] = r
        return out

    # ------------------------------------------------------------ person resolution

    def _holder_of(self, s: Sighting) -> Person | None:
        return self.holder_index.get(id(s))

    def _match(self, s: Sighting, allow_fuzzy: bool = True) -> Person | None:
        key = name_key(s.name)
        exact = list({id(p): p for p in self.key_index.get(key, [])}.values())
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            by_mobile = [p for p in exact if p.mobiles & set(s.mobiles)]
            if len(by_mobile) == 1:
                return by_mobile[0]
            self.report.add("Ambiguous name matches", f"'{s.name}' ({s.source} {s.ref}) matches {len(exact)} people with the same name; first used.")
            return exact[0]
        if not allow_fuzzy:
            return None
        best, best_r = None, 0.0
        for p in self.persons:
            sm = difflib.SequenceMatcher(None, key, p.key)
            if sm.real_quick_ratio() < self.threshold or sm.quick_ratio() < self.threshold:
                continue
            r = sm.ratio()
            if r < self.threshold or r <= best_r:
                continue
            same_mobile = bool(p.mobiles & set(s.mobiles))
            same_district = s.district_code is not None and s.district_code in p.districts
            if same_mobile or same_district:
                best, best_r = p, r
        if best:
            self.report.add("Name variants merged as one person (fuzzy match)",
                            f"'{s.name}' ({s.source} {s.ref}) = '{best.name}' (similarity {best_r:.2f}; "
                            f"{'same mobile' if best.mobiles & set(s.mobiles) else 'same district'})")
        return best

    def _absorb(self, p: Person, s: Sighting) -> None:
        self.order += 1
        s.order = self.order
        p.sightings.append(s)
        self.holder_index[id(s)] = p
        self.key_index.setdefault(name_key(s.name), []).append(p)
        p.mobiles.update(m for m in s.mobiles if len(m) == 10)
        if s.district_code:
            p.districts.add(s.district_code)
        if not p.cadre and s.cadre:
            p.cadre = s.cadre
        if s.email and not p.email:
            p.email = s.email
        if s.priority == P_GRADATION and s.year:
            if p.year and p.year != s.year:
                self.report.add("Conflicting year of joining", f"{p.name}: {p.year} vs {s.year} ({s.source} {s.ref}); first kept")
            else:
                p.year = s.year
                p.dob = p.dob or s.dob
                p.dor = p.dor or s.dor

    def add_sighting(self, s: Sighting, create: bool) -> Person | None:
        p = self._match(s)
        if p is None:
            if not create:
                return None
            p = Person(key=name_key(s.name), name=s.name)
            self.persons.append(p)
        self._absorb(p, s)
        return p

    # ------------------------------------------------------------ build

    def run(self) -> dict:
        r = self.report
        missing = [f for k, f in SOURCES.items() if k not in OPTIONAL_SOURCES and not (self.data / f).exists()]
        for f in missing:
            r.add("Missing inputs", f"`{f}` was not supplied.")
        if self.mdm:
            v = self.mdm["version"]
            r.add("Missing inputs", f"Instead, office IDs come from the **MDM PoC** (`data/mdm_snapshot/`, MDM version "
                  f"{v.get('global')}, updated {v.get('updatedAt')}). Offices MDM does not have keep provisional IDs.")
        elif SOURCES["mdm_reference"] in missing:
            r.add("Missing inputs", "Office IDs are therefore **provisional** (see the office table). "
                  "They follow the spec example `DCO-27NAL`; the `CDO-`/`RCO-` prefixes are invented.")
        r.add("Missing inputs", "`Officer_and_Posting_List.xlsx` was not supplied; the IAS and ACS gradation lists "
              "(August 2026) are used for batch year and current posting instead.")
        if not (self.mdm and self.mdm.get("holiday")):
            r.add("Missing inputs", "No holiday calendar was supplied; `holidays.csv` is empty, so working days exclude Sundays only.")

        dc = parse_dc_list(self.data / SOURCES["dc_list"], self.districts, self.ignored)
        allot = parse_nagaon_allotment(self.data / SOURCES["allotment"], self.districts) if (self.data / SOURCES["allotment"]).exists() else []
        grad = []
        if (self.data / SOURCES["ias"]).exists():
            grad += parse_ias_gradation(self.data / SOURCES["ias"], self.districts)
        if (self.data / SOURCES["acs"]).exists():
            grad += parse_acs_gradation(self.data / SOURCES["acs"], self.districts)
        linked = parse_linked_masters(self.data / SOURCES["linked"]) if (self.data / SOURCES["linked"]).exists() else []
        self.poc = parse_poc_master(self.data / SOURCES["poc_master"], self.districts) \
            if (self.data / SOURCES["poc_master"]).exists() else None

        # 1. Placements, highest-priority source first.
        for s in dc:
            if s.placement:
                self.add_sighting(s, create=True)
            elif s.unmapped_reason:
                r.add("Rows not seeded (no post code)", f"{s.source} {s.ref}: '{s.name}' — {s.unmapped_reason}")
        self._fill_cdc_units(linked)
        for s in allot:
            if s.placement:
                self.add_sighting(s, create=True)
        for s in grad:
            if s.placement:
                self.add_sighting(s, create=True)
        # 2. Enrichment: these rows attach to people already found, never create new ones.
        for s in allot:
            if not s.placement:
                self.add_sighting(s, create=False)
        for s in grad:
            if not s.placement:
                self.add_sighting(s, create=False)
        for s in allot:
            holder = self._holder_of(s)
            if not s.placement and (holder is None or not holder.placements()):
                r.add("Rows not seeded (no post code)", f"{s.source} {s.ref}: '{s.name}' ({s.raw_designation}) — {s.unmapped_reason}")

        self._report_source_disagreements(grad)
        chairs = self._choose_chairs()
        offices = self._offices(chairs)
        self._geo_crosswalk(offices)
        self._mdm_crosswalk(offices)
        self._dept_offices(offices, chairs)
        self._check_department_names()
        allotments = self._nagaon_allotments(allot, chairs)
        self._demo_function_holders(offices, chairs, allotments)
        self._demo_bundles(offices, chairs, allotments)
        self._demo_sub_registrars(offices, chairs)
        self._cross_check(linked, chairs)
        self._report_mobiles()
        return self._write(offices, chairs, allotments)

    def _fill_cdc_units(self, linked) -> None:
        for p in self.persons:
            for s in p.placements():
                if s.post_code == "CDC" and not s.unit:
                    hit = next((lo for lo in linked if name_key(lo.name) == p.key and "Co-District" in lo.office_name), None)
                    if hit:
                        s.unit = hit.office_name.split(",")[-1].strip()
                        self.report.add("Gaps filled from the earlier PoC (cross-check file)",
                                        f"{s.source} {s.ref}: CDC '{p.name}' has no co-district in the list; "
                                        f"`{SOURCES['linked']}` places them at {s.unit}.")
                    else:
                        s.placement = False
                        self.report.add("Rows not seeded (no post code)", f"{s.source} {s.ref}: CDC '{p.name}' has no co-district named; not seeded.")

    def _office_key(self, s: Sighting) -> tuple:
        return (s.office_type, s.district_code, (s.unit or "").strip())

    def _report_source_disagreements(self, grad: list[Sighting]) -> None:
        heads = {}
        for p in self.persons:
            for s in p.placements():
                if s.priority == P_DC_LIST and s.post_code in ("DC", "CDC"):
                    heads[(s.post_code, s.district_code, name_key(s.unit or ""))] = p
        for s in grad:
            if s.post_code in ("DC", "CDC") and s.district_code and not s.placement:
                holder = heads.get((s.post_code, s.district_code, name_key(s.unit or "")))
                if holder and name_key(s.name) != holder.key and self._holder_of(s) is not holder:
                    self.report.add("Source disagreements (List_of_DCs.xlsx used)",
                                    f"{s.post_code} {s.unit} ({self.dist_by_code[s.district_code].name}): gradation list "
                                    f"({s.source} {s.ref}) names '{s.name}'; List_of_DCs.xlsx names '{holder.name}'.")

    def _choose_chairs(self) -> list[Chair]:
        chairs: list[Chair] = []
        for p in self.persons:
            places = p.placements()
            if not places:
                continue
            places.sort(key=lambda s: (s.priority, self.rank[s.post_code], s.order))
            primary = places[0]
            chairs.append(Chair(self._office_key(primary), primary.post_code, p, f"{primary.source} {primary.ref}"))
            seen = {(self._office_key(primary), primary.post_code)}
            for s in places[1:]:
                k = (self._office_key(s), s.post_code)
                if k in seen:
                    continue
                seen.add(k)
                where = f"{s.post_code} at {s.unit} ({self.dist_by_code[s.district_code].name})"
                used = f"{primary.post_code} at {primary.unit} ({self.dist_by_code[primary.district_code].name})"
                section = ("Officer listed in two offices" if s.priority == primary.priority
                           else "Conflicting postings across sources")
                if s.priority == P_DC_LIST:
                    gap = Person(key=f"demo-gap-{len(chairs)}", name="", is_demo=True,
                                 note=f"Fills the chair List_of_DCs.xlsx gives to {p.name} ({s.ref}), who is seeded at {used}.")
                    chairs.append(Chair(k[0], s.post_code, gap, f"{s.source} {s.ref}", is_demo=True))
                    self.report.add(section, f"'{p.name}': {s.source} {s.ref} says {where}; seeded at {used} "
                                             f"({primary.source} {primary.ref}). The {where} chair is filled by a demo officer.")
                else:
                    self.report.add(section, f"'{p.name}': {s.source} {s.ref} says {where}; seeded at {used} "
                                             f"({primary.source} {primary.ref}, higher-priority source).")
        return chairs

    def _new_office(self, otype: str, dcode: str, unit: str, source: str) -> dict:
        d = self.dist_by_code[dcode]
        letters = re.sub(r"[^A-Z]", "", unit.upper())
        candidates = [letters[:3], letters[:2] + letters[-1:], letters[0] + letters[2:4]] + [f"{letters[:2]}{n}" for n in range(2, 10)]
        oid = next(f"{OFFICE_PREFIX[otype]}-{dcode}{c}" for c in candidates
                   if f"{OFFICE_PREFIX[otype]}-{dcode}{c}" not in self.used_office_ids)
        self.used_office_ids.add(oid)
        mdm_type = self.mdm_cfg.get("office_type_map", {}).get(otype, otype)
        return dict(office_id=oid, name=OFFICE_NAME[otype].format(unit), office_type=mdm_type, district_code=dcode,
                    district_name=d.name, parent_office_id=f"DCO-{dcode}{d.abbr}", establishment_actor=f"ESTB@{oid}",
                    provisional=True, external_ref="", source=f"{source} (MDM office seed not supplied)")

    def _offices(self, chairs: list[Chair]) -> dict[tuple, dict]:
        offices: dict[tuple, dict] = {}
        for d in self.districts:
            key = ("DC_OFFICE", d.code, d.name)
            oid = f"DCO-{d.code}{d.abbr}"
            geo = self.poc.geo_district_codes.get(d.code) if self.poc else None
            offices[key] = dict(office_id=oid, name=OFFICE_NAME["DC_OFFICE"].format(d.name), office_type="DC_OFFICE",
                                district_code=d.code, district_name=d.name, parent_office_id="",
                                establishment_actor=f"ESTB@{oid}", provisional=True,
                                external_ref=f"PoC_master_data.xlsx Geo Master district {geo}" if geo else "",
                                source="derived from List_of_DCs.xlsx (MDM office seed not supplied)")
            self.used_office_ids.add(oid)
        for ch in sorted(chairs, key=lambda c: (c.office_key[1], c.office_key[0], c.office_key[2])):
            if ch.office_key not in offices:
                otype, dcode, unit = ch.office_key
                offices[ch.office_key] = self._new_office(otype, dcode, unit, f"derived from {ch.source}")
        return offices

    def _geo_crosswalk(self, offices: dict) -> None:
        """Match revenue-circle offices to the Geo Master circle list (PoC_master_data.xlsx). Matches get an
        external_ref; Geo Master circles with no officer on the roster become offices with no chairs."""
        if self.poc is None:
            return
        sec = "Circle offices cross-walked to PoC_master_data.xlsx Geo Master"

        def score(a: str, b: str) -> float:
            a, b = norm_place(a), norm_place(b)
            if a == b:
                return 1.0
            if a and b and (a in b or b in a):
                return 0.95
            return similarity(a, b)

        for dcode in sorted({c.district_code for c in self.poc.circles}):
            ours = [(k, o) for k, o in offices.items() if k[0] == "CIRCLE_OFFICE" and k[1] == dcode]
            geo = [c for c in self.poc.circles if c.district_code == dcode]
            pairs = sorted(((score(k[2], g.circle_name), i, j) for i, (k, _) in enumerate(ours) for j, g in enumerate(geo)),
                           reverse=True)
            used_o, used_g = set(), set()
            for sc, i, j in pairs:
                if sc < 0.75 or i in used_o or j in used_g:
                    continue
                used_o.add(i)
                used_g.add(j)
                key, office = ours[i]
                g = geo[j]
                office["external_ref"] = f"PoC_master_data.xlsx Geo Master {g.circle_code} {g.circle_name}"
                if sc < 1.0:
                    self.report.add(sec, f"{office['office_id']} '{key[2]}' (List_of_DCs.xlsx) = {g.circle_code} "
                                         f"'{g.circle_name}' (spelling differs; MDM to settle the official name)")
            for j, g in enumerate(geo):
                if j in used_g:
                    continue
                unit = g.circle_name.title()
                o = self._new_office("CIRCLE_OFFICE", dcode, unit, "PoC_master_data.xlsx Geo Master")
                o["external_ref"] = f"PoC_master_data.xlsx Geo Master {g.circle_code} {g.circle_name}"
                offices[("CIRCLE_OFFICE", dcode, unit)] = o
                self.report.add("Circle offices with no officer on the roster",
                                f"{o['office_id']} '{unit}' ({g.circle_code}): in the Geo Master circle list, but no Circle "
                                f"Officer is named in List_of_DCs.xlsx. Office seeded with no chairs; seat lookups there "
                                f"return NO_HOLDER until a posting is entered.")
            for i, (key, office) in enumerate(ours):
                if i not in used_o:
                    self.report.add(sec, f"{office['office_id']} '{key[2]}' has no match in the Geo Master circle list.")

    def _mdm_crosswalk(self, offices: dict) -> None:
        """Replace derived office IDs with MDM office codes. MDM offices in the PoC districts that no officer on
        the roster sits in are added with no chairs; derived offices MDM lacks keep their provisional IDs."""
        if not self.mdm:
            return
        sec = "Offices cross-walked to the MDM PoC"
        type_map = self.mdm_cfg.get("office_type_map", {})
        ver = self.mdm["version"].get("global")
        by_district = defaultdict(list)
        for rec in self.mdm["office"]:
            by_district[rec.get("districtCode")].append(rec)
        dc_ids = {}
        for d in self.districts:
            mdm_recs = by_district.get(d.mdm_code, [])
            ours = [(k, o) for k, o in offices.items() if k[1] == d.code]
            scores = [(place_score(k[2], office_unit_name(rec["name"], self.mdm_cfg)), i, j)
                      for i, (k, _) in enumerate(ours) for j, rec in enumerate(mdm_recs)
                      if rec["officeTypeCode"] == type_map.get(k[0], k[0])]
            matched_ours, matched_mdm = set(), set()
            for sc, i, j in greedy_pairs(scores):
                (k, o), rec = ours[i], mdm_recs[j]
                matched_ours.add(i)
                matched_mdm.add(j)
                old = o["office_id"]
                o.update(office_id=rec["code"], name=rec["name"], office_type=rec["officeTypeCode"],
                         district_code=rec.get("districtCode") or d.mdm_code, district_name=rec.get("districtName"),
                         parent_office_id=rec.get("parentOfficeCode") or "", establishment_actor=f"ESTB@{rec['code']}",
                         provisional=False, is_active=bool(rec.get("isActive", True)), mdm_id=rec.get("id"),
                         source=f"MDM office {rec['code']} (snapshot version {ver})")
                self.used_office_ids.add(rec["code"])
                if k[0] == "DC_OFFICE":
                    dc_ids[d.code] = rec["code"]
                if sc < 1.0:
                    self.report.add(sec, f"'{k[2]}' (sources) = MDM {rec['code']} '{rec['name']}' (spelling differs; "
                                         f"provisional ID would have been {old})")
            for i, (k, o) in enumerate(ours):
                if i not in matched_ours:
                    o["district_code"] = d.mdm_code or o["district_code"]
                    o["office_type"] = type_map.get(o["office_type"], o["office_type"])
                    self.report.add("Offices not in MDM (provisional IDs kept)",
                                    f"{o['office_id']} '{o['name']}' ({d.name}): no {o['office_type']} of that name in MDM.")
            added = []
            for j, rec in enumerate(mdm_recs):
                if j in matched_mdm:
                    continue
                offices[("MDM", d.code, rec["code"])] = dict(
                    office_id=rec["code"], name=rec["name"], office_type=rec["officeTypeCode"],
                    district_code=rec.get("districtCode"), district_name=rec.get("districtName"),
                    parent_office_id=rec.get("parentOfficeCode") or "", establishment_actor=f"ESTB@{rec['code']}",
                    provisional=False, external_ref="", is_active=bool(rec.get("isActive", True)), mdm_id=rec.get("id"),
                    source=f"MDM office {rec['code']} (snapshot version {ver})")
                added.append(rec["code"])
            if added:
                self.report.add("MDM offices with no officer on the HR roster (added with no chairs)",
                                f"{d.name}: {', '.join(sorted(added))}")
        for o in offices.values():  # provisional offices point at their district's MDM DC office
            if o.get("provisional") and o.get("parent_office_id", "").startswith("DCO-"):
                num = o["parent_office_id"][4:6]
                o["parent_office_id"] = dc_ids.get(num, o["parent_office_id"])
        posts_missing = [p for p, r in self.posts.items() if r.get("mdm_designation_code")
                         and r["mdm_designation_code"] not in {x["code"] for x in self.mdm["designation"]}]
        for p, r in self.posts.items():
            code = r.get("mdm_designation_code")
            self.report.add("Posts mapped to MDM designations",
                            f"{p} → {code}" + (" (NOT FOUND in MDM)" if p in posts_missing else "") if code
                            else f"{p} → no MDM designation yet")

    def _check_department_names(self) -> None:
        if self.poc is None:
            return
        official = {norm_place(x) for x in self.poc.official_depts}
        sec = "Issuing departments checked against the official department list"
        checked = []
        for cadre, dept in sorted(self.issuing.items()):
            if dept.startswith("UNKNOWN"):
                continue
            core = norm_place(re.sub(r"(?i)\bdepartment\b|\bof\b", "", dept))
            if core in official:
                checked.append(dept)
            else:
                self.report.add(sec, f"'{dept}' (cadre {cadre}) is not on the Official Dept List in PoC_master_data.xlsx.")
        if checked:
            self.report.add(sec, f"On the Official Dept List: {', '.join(sorted(set(checked)))}.")

    def _dept_offices(self, offices: dict, chairs: list[Chair]) -> None:
        for o in self.cfg["department_offices"]:
            key = (o["office_type"], o["district_code"], o["office_id"])
            dname = self.dist_by_code[o["district_code"]].name if o["district_code"] in self.dist_by_code else "State level"
            name, source = o["name"], "spec section 9 (office ID given in the spec)"
            dept = self.poc.dept_names.get(o.get("mdm_dept_code", "")) if self.poc else None
            if dept and o.get("name_from_dept"):
                name = o["name_from_dept"].format(dept=dept)
                source += f"; name from PoC_master_data.xlsx Service ID Blocks ({o['mdm_dept_code']})"
                self.report.add("Names taken from PoC_master_data.xlsx",
                                f"{o['office_id']}: department code {o['mdm_dept_code']} = '{dept}'.")
            mdm_district = self.dist_by_code[o["district_code"]].mdm_code if o["district_code"] in self.dist_by_code else "AS"
            in_mdm = next((r for r in (self.mdm or {}).get("office", []) if r["code"] == o["office_id"]), None)
            if in_mdm:  # MDM has it now: use MDM's record (and drop the copy the MDM cross-walk added)
                for k in [k for k, v in offices.items() if v["office_id"] == o["office_id"]]:
                    del offices[k]
                name, source = in_mdm["name"], f"MDM office {in_mdm['code']}"
            elif self.mdm:
                self.report.add("Offices not in MDM (provisional IDs kept)",
                                f"{o['office_id']} '{name}': the MDM PoC has no such office yet.")
            offices[key] = dict(office_id=o["office_id"], name=name, office_type=o["office_type"],
                                district_code=mdm_district if self.mdm else o["district_code"], district_name=dname,
                                parent_office_id="", establishment_actor=f"ESTB@{o['office_id']}",
                                provisional=bool(self.mdm) and not in_mdm,
                                external_ref=f"PoC_master_data.xlsx dept {o['mdm_dept_code']}" if dept else "",
                                is_active=True, mdm_id=in_mdm.get("id") if in_mdm else None, source=source)
            for post in o["posts"]:
                p = Person(key=f"demo-dept-{o['office_id']}-{post}", name="", cadre=o["cadre"], is_demo=True,
                           note=f"No officer data supplied for {o['office_id']}; demo {post}.")
                chairs.append(Chair(key, post, p, "spec section 9", is_demo=True))
                self.report.add("Demo officers (no source data)", f"{o['office_id']} {post}: no officer named in any source; demo officer seeded.")

    def _functions_for(self, items: list[str], who: str) -> list[str]:
        codes = []
        for item in items:
            code = next((c for rx, c in self.branch_map if rx.search(item)), None)
            if code is None:
                self.report.add("Nagaon allotment lines not mapped to a function", f"{who}: '{item}'")
            elif code != "IGNORE" and code not in codes:
                codes.append(code)
        return codes

    def _nagaon_allotments(self, allot: list[Sighting], chairs: list[Chair]) -> list[dict]:
        out = []
        office_of = {id(c.holder): c.office_key for c in chairs}
        for s in allot:
            p = self._holder_of(s)
            codes = self._functions_for(s.functions_text, s.name)
            if not codes:
                continue
            okey = office_of.get(id(p)) if p else None
            if not okey or okey != ("DC_OFFICE", "26", "Nagaon"):
                self.report.add("Nagaon allotments not seeded (BR-04: no posting in DCO Nagaon)",
                                f"'{s.name}' ({s.raw_designation}): {', '.join(codes)}")
                continue
            for code in codes:
                out.append(dict(person=p, office_key=okey, function_code=code, is_demo=False,
                                source_ref=f"{SOURCES['allotment']} {s.ref}; {self.cfg['nagaon_allotment_order_ref']}"))
        return out

    def _demo_function_holders(self, offices: dict, chairs: list[Chair], allotments: list[dict]) -> None:
        required = self.cfg["demo_functions_required_in_dc_offices"]
        for d in self.districts:
            okey = ("DC_OFFICE", d.code, d.name)
            held = {a["function_code"] for a in allotments if a["office_key"] == okey}
            missing = [f for f in required if f not in held]
            if not missing:
                continue
            groups = [g for g in ([f for f in missing if f != "ARTPS"], [f for f in missing if f == "ARTPS"]) if g]
            for n, fns in enumerate(groups, start=1):
                p = Person(key=f"demo-fn-{d.code}-{n}", name=f"Demo Officer {d.abbr}-{n}", cadre="DEMO", is_demo=True,
                           note=f"Synthetic ADC so DCO {d.name} has a holder of {', '.join(fns)}.")
                chairs.append(Chair(okey, "ADC", p, "demo (no real allotment)", is_demo=True))
                for f in fns:
                    allotments.append(dict(person=p, office_key=okey, function_code=f, is_demo=True,
                                           source_ref="DEMO allotment: no real work-allotment order for this office"))
                self.report.add("Demo officers for function coverage",
                                f"{offices[okey]['office_id']}: no real allotment of {', '.join(fns)}; demo ADC '{p.name}' seeded holding it.")

    def _demo_bundles(self, offices: dict, chairs: list[Chair], allotments: list[dict]) -> None:
        """Give real ADCs and ACs a demo function bundle in offices that have no real allotment order."""
        sec = "Demo function bundles (offices with no real allotment order)"
        with_order = {a["office_key"] for a in allotments if not a["is_demo"]}
        for okey, office in sorted(offices.items(), key=lambda kv: kv[1]["office_id"]):
            if okey in with_order:
                continue
            for post, rule in self.post_rules.items():
                bundles = self.bundles.get((office["office_type"], post))
                if rule["mode"] != "ALLOTTED" or not bundles:
                    continue
                holders = sorted((c.holder for c in chairs if c.office_key == okey and c.post_code == post
                                  and not c.holder.is_demo), key=seniority)
                for i, person in enumerate(holders):
                    b = bundles[i % len(bundles)]
                    for f in b["functions"]:
                        allotments.append(dict(person=person, office_key=okey, function_code=f, is_demo=True,
                                               source_ref=f"DEMO bundle {office['office_type']}/{post}/{b['bundle']} ({b['basis']})"))
                    self.report.add(sec, f"{office['office_id']} {post} '{person.name}': bundle {b['bundle']} = "
                                         f"{', '.join(b['functions'])}")
        for code in self.post_rules:
            if self.post_rules[code]["mode"] == "ALL_OFFICE_FUNCTIONS":
                self.report.add("Posts that hold every function of their office (no allotment rows)",
                                f"{code}: {self.post_rules[code]['basis']}")

    def _demo_sub_registrars(self, offices: dict, chairs: list[Chair]) -> None:
        """One demo Sub Registrar in every circle office that has a CO on the roster (Link Officer for a lone CO)."""
        post = self.cfg.get("demo_sub_registrar_post")
        if not post or post not in self.posts:
            return
        with_co = sorted({c.office_key for c in chairs if c.post_code == "CO"
                          and offices[c.office_key]["office_type"] == "CIRCLE_OFFICE"},
                         key=lambda k: offices[k]["office_id"])
        for okey in with_co:
            unit = okey[2]
            p = Person(key=f"demo-sr-{offices[okey]['office_id']}", name=f"Demo Sub Registrar, {unit}", cadre="DEMO_SR",
                       is_demo=True, note=self.cfg.get("demo_sub_registrar_reason"))
            chairs.append(Chair(okey, post, p, "demo Sub Registrar (no source names one)", is_demo=True))
        self.report.add("Demo Sub Registrars (Link Officer for a lone Circle Officer)",
                        f"{len(with_co)} circle offices with a CO each get a demo Sub Registrar ({post}): "
                        f"{', '.join(offices[k]['office_id'] for k in with_co)}. {self.cfg.get('demo_sub_registrar_reason', '')}")

    def _cross_check(self, linked, chairs: list[Chair]) -> None:
        by_key = {c.holder.key: c for c in chairs if not c.holder.is_demo}
        for lo in linked:
            c = by_key.get(name_key(lo.name))
            if c is None:
                hits = [p for p in self.persons if similarity(name_key(lo.name), p.key) >= self.threshold]
                c = next((by_key.get(h.key) for h in hits if h.key in by_key), None)
            if c is None:
                self.report.add("Cross-check against Sewa_Setu_PoC_Linked_Masters.xlsx",
                                f"{lo.officer_id} '{lo.name}' ({lo.post_text}, {lo.office_name}) is not on the current roster.")
                continue
            unit = c.office_key[2]
            if lo.district and self.dist_by_code[c.office_key[1]].name != lo.district or (
                    unit.split()[0].lower()[:4] not in lo.office_name.lower() and c.office_key[0] != "DC_OFFICE"):
                self.report.add("Cross-check against Sewa_Setu_PoC_Linked_Masters.xlsx",
                                f"{lo.officer_id} '{lo.name}': earlier PoC had {lo.post_text} at {lo.office_name}; "
                                f"now seeded as {c.post_code} at {unit}.")

    def _report_mobiles(self) -> None:
        owners = defaultdict(set)
        for p in self.persons:
            for s in p.sightings:
                for m in s.mobiles:
                    if len(m) == 10:
                        owners[m].add(p.name)
                    else:
                        self.report.add("Invalid mobile numbers", f"'{p.name}' ({s.source} {s.ref}): '{m}' is not 10 digits")
        for m, names in sorted(owners.items()):
            if len(names) > 1:
                self.report.add("Shared mobile numbers (distinct people)", f"{m}: {', '.join(sorted(names))}")

    # ------------------------------------------------------------ output

    def _write(self, offices: dict, chairs: list[Chair], allotments: list[dict]) -> dict:
        # The roster plan: what the sources say, keyed by roster-person keys (R-NNNNNN). seed.mdm_load sends it to
        # MDM (which mints the Employee IDs) and seed.bind turns it into the HR seed under MDM codes.
        mdm_dir = hr_dir = self.data / "roster_plan"
        # Number gap/dept demo officers, then key people: real people in discovery order, demos after.
        demo_n = 0
        for c in chairs:
            if c.holder.is_demo and not c.holder.name:
                demo_n += 1
                c.holder.name = f"Demo Officer G{demo_n:02d}"
                c.holder.cadre = c.holder.cadre or "DEMO"
        real = [c.holder for c in chairs if not c.holder.is_demo]
        demos = [c.holder for c in chairs if c.holder.is_demo]
        for n, p in enumerate(real + demos, start=1):
            p.employee_id = f"R-{n:06d}"

        sanctioned, postings = [], []
        by_office_post = defaultdict(list)
        for c in chairs:
            by_office_post[(c.office_key, c.post_code)].append(c)
        chair_id = {}
        for (okey, post), group in sorted(by_office_post.items(), key=lambda kv: (offices[kv[0][0]]["office_id"], self.rank[kv[0][1]], kv[0][1])):
            oid = offices[okey]["office_id"]
            for seq, c in enumerate(sorted(group, key=lambda c: seniority(c.holder)), start=1):
                spid = f"{oid}-{post}-{seq:02d}"
                chair_id[id(c)] = spid
                sanctioned.append(dict(sanctioned_post_id=spid, office_id=oid, post_code=post, seq=seq, derived=True,
                                       is_demo=c.is_demo, source=c.source))
                cadre = c.holder.cadre or "UNKNOWN"
                joined = next((s.joined for s in c.holder.sightings if s.joined), None)
                postings.append(dict(
                    employee_id=c.holder.employee_id, sanctioned_post_id=spid, charge_type="SUBSTANTIVE",
                    effective_from=self.cfg["posting_effective_from"],
                    order_ref=f"SEED-SNAPSHOT (not an order): {c.source}",
                    issuing_department=self.issuing.get(cadre, self.issuing["UNKNOWN"]),
                    note="; ".join(x for x in (c.holder.note, f"source date of joining: {joined}" if joined else None) if x),
                ))
        office_rows = sorted(offices.values(), key=lambda o: o["office_id"])
        employees = []
        for p in real + demos:
            employees.append(dict(
                employee_id=p.employee_id, name=p.name, cadre=p.cadre or "UNKNOWN", year_of_joining=p.year,
                date_of_birth=p.dob, date_of_retirement=p.dor, email=p.email,
                mobile=next(iter(sorted(p.mobiles)), None), finassam_code=None, pan=None, aadhaar_token_hash=None,
                is_demo=p.is_demo, source="; ".join(sorted({f"{s.source} {s.ref}" for s in p.sightings})) or p.note,
            ))
            if not p.is_demo and p.year is None:
                self.report.add("Officers with no year of joining (seniority falls back to name)",
                                f"{p.employee_id} {p.name} ({p.cadre or 'cadre unknown'})")
        allot_rows = [dict(employee_id=a["person"].employee_id, office_id=offices[a["office_key"]]["office_id"],
                           function_code=a["function_code"], effective_from=self.cfg["nagaon_allotment_effective_from"],
                           is_demo=a["is_demo"], source_ref=a["source_ref"]) for a in allotments]

        _write_csv(mdm_dir / "offices.csv", ["office_id", "name", "office_type", "district_code", "district_name",
                                              "parent_office_id", "establishment_actor", "provisional", "external_ref",
                                              "is_active", "mdm_id", "source"],
                   [{"is_active": True, **o} for o in office_rows])
        _write_csv(mdm_dir / "posts.csv", ["post_code", "name", "rank_order", "mdm_designation_code", "source"],
                   list(self.posts.values()))
        mdm_designations = self.mdm["designation"] if self.mdm else []
        _write_csv(mdm_dir / "designations.csv", ["code", "name", "level", "department_code", "is_active", "mdm_id"],
                   [dict(code=d["code"], name=d["name"], level=d.get("level"), department_code=d.get("departmentCode"),
                         is_active=bool(d.get("isActive", True)), mdm_id=d.get("id")) for d in mdm_designations])
        _write_csv(mdm_dir / "sanctioned_posts.csv", ["sanctioned_post_id", "office_id", "post_code", "seq", "derived",
                                                       "is_demo", "source"], sanctioned)
        _write_csv(mdm_dir / "function_codes.csv", ["code", "name", "category", "source"], self.function_codes)
        _write_csv(mdm_dir / "office_type_functions.csv", ["office_type", "function_code", "is_demo", "source"],
                   [dict(office_type=t, function_code=c, is_demo=r["is_demo"] == "True", source=r["basis"])
                    for t, fns in sorted(self.catalogue.items()) for c, r in sorted(fns.items())])
        _write_csv(mdm_dir / "post_function_rules.csv", ["post_code", "mode", "is_demo", "source"],
                   [dict(post_code=p, mode=r["mode"], is_demo=r["is_demo"] == "True", source=r["basis"])
                    for p, r in self.post_rules.items()])
        _write_csv(mdm_dir / "employees.csv", ["employee_id", "name", "cadre", "year_of_joining", "date_of_birth",
                                                "date_of_retirement", "email", "mobile", "finassam_code", "pan",
                                                "aadhaar_token_hash", "is_demo", "source"], employees)
        mdm_holidays = self.mdm["holiday"] if self.mdm else []
        _write_csv(mdm_dir / "holidays.csv", ["code", "holiday_date", "name", "holiday_type", "district_code", "is_active",
                                               "source"],
                   [dict(code=h["code"], holiday_date=h["date"], name=h["name"], holiday_type=h.get("holidayType"),
                         district_code=h.get("districtCode"), is_active=bool(h.get("isActive", True)),
                         source=f"MDM holiday {h['code']}") for h in mdm_holidays])
        _write_csv(hr_dir / "postings.csv", ["employee_id", "sanctioned_post_id", "charge_type", "effective_from",
                                              "order_ref", "issuing_department", "note"], postings)
        _write_csv(hr_dir / "function_allotments.csv", ["employee_id", "office_id", "function_code", "effective_from",
                                                         "is_demo", "source_ref"], allot_rows)
        summary = dict(
            offices=len(office_rows), chairs=len(sanctioned), officers=len(employees),
            demo_officers=sum(1 for e in employees if e["is_demo"]),
            real_officers=sum(1 for e in employees if not e["is_demo"]),
            allotments=len(allot_rows), demo_allotments=sum(1 for a in allot_rows if a["is_demo"]),
            by_type={t: sum(1 for o in office_rows if o["office_type"] == t) for t in sorted({o["office_type"] for o in office_rows})},
        )
        self._write_report(summary, office_rows, sanctioned, employees)
        return summary

    def _write_report(self, summary, offices, sanctioned, employees) -> None:
        demo_pct = 100.0 * summary["demo_officers"] / max(summary["officers"], 1)
        lines = [
            "# Seed load report",
            "",
            f"Generated {datetime.now().strftime('%d-%m-%Y %H:%M')} by `python -m seed.build`. "
            "Every judgement the builder made is listed here; nothing was filled silently.",
            "",
            "## Summary",
            "",
            "| Item | Count |", "|---|---|",
            f"| Offices | {summary['offices']} ({', '.join(f'{k}: {v}' for k, v in summary['by_type'].items())}) |",
            f"| Chairs (sanctioned posts, all `derived = true`) | {summary['chairs']} |",
            f"| Officers | {summary['officers']} (real {summary['real_officers']}, demo {summary['demo_officers']} = {demo_pct:.1f}%) |",
            f"| Function allotments | {summary['allotments']} (demo {summary['demo_allotments']}) |",
            "",
            "Source priority when sources disagree: `List_of_DCs.xlsx` > Nagaon work-allotment order > "
            "IAS/ACS gradation lists. Gradation lists add ADC and AC holders (the DC list names only one ADC "
            "per district) and supply batch year for seniority. DC, CDC and CO chairs come only from `List_of_DCs.xlsx`.",
            "",
        ]
        for section, items in self.report.sections.items():
            lines += [f"## {section}", ""] + [f"- {i}" for i in items] + [""]
        lines += ["## Ignored data", ""]
        lines.append(f"- `List_of_DCs.xlsx` sheet `COs`: {self.ignored.get('co_sheet_rows_with_unlabelled_columns_G_to_I', 0)} rows "
                     "carry a second, unlabelled name list in columns G–I. With no header to say what it means, it is ignored.")
        lines.append("- Districts outside the PoC (all but Nalbari, Kamrup Metropolitan, Dhubri, Tinsukia, Nagaon) are ignored.")
        lines.append("- Gradation-list postings outside PoC offices are used only to enrich officers already found (year, DOB, email).")
        if self.poc is not None:
            codes = ", ".join(f"{self.dist_by_code[k].name} {v}" for k, v in sorted(self.poc.geo_district_codes.items()))
            lines.append(f"- `PoC_master_data.xlsx` **Officer Directory** ({self.poc.officer_rows} rows) is not imported: its "
                         "header says 'Officer Name (Demo)', mobiles are sequential and names repeat across posts, so the "
                         "people are synthetic. Using them would fill gaps silently.")
            lines.append("- `PoC_master_data.xlsx` sheets that map services and posts to ARTPS authority roles (Sheet1, "
                         "Post Master, DPS Tier Map, Change Log, HR Validation) are not imported: roles belong to the Rule Engine.")
            lines.append(f"- `PoC_master_data.xlsx` uses a third district-code scheme ({codes}); kept as `external_ref` "
                         "on DC offices only. Office IDs keep the spec's numeric codes.")
        lines += ["", "## Offices (provisional IDs)", "",
                  "| office_id | name | type | provisional | external_ref |", "|---|---|---|---|---|"]
        lines += [f"| {o['office_id']} | {o['name']} | {o['office_type']} | {o['provisional']} | {o.get('external_ref') or ''} |"
                  for o in offices]
        (self.data / "load_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(data_dir: Path = DEFAULT_DATA) -> dict:
    return Builder(data_dir).run()


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(build(), indent=2))
