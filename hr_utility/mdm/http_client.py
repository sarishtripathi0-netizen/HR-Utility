"""HttpMdmClient: the live adapter to the MDM PoC (MDM api.md / integration.md, "HR Utility contract").

MDM owns offices, designations, cadres, functions, office-type and designation functions, sanctioned strength,
Link Officer rules, employees (minted by MDM) and holidays. All are read from MDM snapshots and mapped by
hr_utility.mdm.workforce exactly as the offline client maps a saved snapshot. Only the local overlay (demo
officers, demo chairs, offices MDM lacks, HR-only attributes, the ARTPS condition) is read from disk.
"""
from __future__ import annotations

import time

import httpx

from .client import EmployeeRec, MintPayload, MintResult, SanctionedPostRec
from .mapping import snapshot_records
from .seed_client import HR_EMPLOYEE_FIELDS, MDM_EMPLOYEE_FIELDS, ChairError, WorkforceClient
from .workforce import WORKFORCE_TYPES, chair_id


class HttpMdmClient(WorkforceClient):
    SNAPSHOT_TTL_S = 20.0  # one refresh reads each type once

    def __init__(self, base_url: str, data_dir, minted_store, timeout: float = 10.0, transport=None,
                 actor: str = "hr-utility-poc"):
        super().__init__(data_dir, minted_store)
        self.base_url = base_url.rstrip("/")
        self.actor = actor
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)
        self._cache: tuple[float, dict] | None = None

    # ------------------------------------------------------------ transport

    def _get(self, path: str, **params) -> dict:
        r = self._http.get(path, params=params or None)
        r.raise_for_status()
        return r.json()

    def _write(self, method: str, path: str, body: dict, reason: str) -> httpx.Response:
        self._cache = None
        return self._http.request(method, path, json=body, headers={"X-User": self.actor, "X-Change-Reason": reason})

    def health(self) -> dict:
        return self._get("/health")

    def version(self) -> dict:
        return self._get("/mdm/version")

    def snapshot(self, entity_type: str) -> list[dict]:
        return snapshot_records(self._get(f"/mdm/snapshot/{entity_type}", includeInactive="true"))

    def _snapshot(self) -> dict[str, list[dict]]:
        if self._cache and time.monotonic() - self._cache[0] < self.SNAPSHOT_TTL_S:
            return self._cache[1]
        snap = {t: self.snapshot(t) for t in WORKFORCE_TYPES}
        self._cache = (time.monotonic(), snap)
        return snap

    def register_consumer(self, code: str, name: str, usage_url: str, actor: str) -> dict:
        r = self._write("POST", "/mdm/consumers", {"code": code, "name": name, "usageUrl": usage_url},
                        "HR Utility PoC consumer registration")
        r.raise_for_status()
        return r.json()

    def validate(self, refs: dict[str, list[str]], as_on: str | None = None) -> dict:
        r = self._http.post("/mdm/validate", json={"refs": refs, **({"asOn": as_on} if as_on else {})})
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------ writes (MDM owns these)

    def mint_employee(self, payload: MintPayload) -> MintResult:
        body = {"name": payload.name, "gender": payload.gender, "mobile": payload.mobile, "email": payload.email,
                "cadreCode": payload.cadre, "dateOfJoining": payload.date_of_joining}
        r = self._write("POST", "/mdm/employees/mint", {k: v for k, v in body.items() if v}, "HR Utility onboarding")
        if r.status_code == 409:
            people = self.snapshot("employee")
            for key, value in (("MOBILE", payload.mobile), ("EMAIL", payload.email)):
                hit = next((e for e in people if value and (e.get(key.lower()) or "").lower() == value.lower()), None)
                if hit:
                    return MintResult(hit["code"], duplicate=True, matched_on=key, message=r.text[:300])
            return MintResult(None, duplicate=True, matched_on="MDM", message=r.text[:300])
        r.raise_for_status()
        code = r.json()["record"]["code"]
        self._save_hr_fields(code, payload.__dict__, payload.source or "mint")
        return MintResult(code, duplicate=False)

    def update_employee(self, employee_id: str, changes: dict, actor: str) -> EmployeeRec:
        with self._lock:
            if self._is_local_employee(employee_id):
                self._append(self.extra_store, {"employee_id": employee_id, "changes": changes, "by": actor})
            else:
                mdm = {MDM_EMPLOYEE_FIELDS[k]: v for k, v in changes.items() if k in MDM_EMPLOYEE_FIELDS}
                if mdm:
                    r = self._write("PUT", f"/mdm/entities/employee/{employee_id}", mdm, f"HR correction by {actor}")
                    if r.status_code == 404:
                        raise KeyError(employee_id)
                    if r.status_code >= 400:
                        raise ValueError(f"MDM refused the correction: {r.text[:300]}")
                self._save_hr_fields(employee_id, {k: v for k, v in changes.items() if k in HR_EMPLOYEE_FIELDS}, actor)
        rec = self.get_employee(employee_id)
        if rec is None:
            raise KeyError(employee_id)
        return rec

    def add_sanctioned_post(self, office_id: str, post_code: str, source: str) -> SanctionedPostRec:
        code = f"{office_id}:{post_code}"
        got = self._http.get(f"/mdm/entities/sanctioned-post/{code}")
        if got.status_code == 200:
            n = int(got.json()["sanctionedCount"]) + 1
            r = self._write("PUT", f"/mdm/entities/sanctioned-post/{code}", {"sanctionedCount": n}, source)
        else:
            n = 1
            r = self._write("POST", "/mdm/entities/sanctioned-post",
                            {"officeCode": office_id, "designationCode": post_code, "sanctionedCount": 1}, source)
        if r.status_code >= 400:
            raise ChairError(f"MDM refused the new chair: {r.text[:300]}")
        return SanctionedPostRec(chair_id(office_id, post_code, n), office_id, post_code, n, derived=False, is_demo=False,
                                 source=f"MDM sanctioned-post {code} ({n})")

    def abolish_sanctioned_post(self, sanctioned_post_id: str, reason: str) -> SanctionedPostRec:
        chair = self._top_chair(sanctioned_post_id)
        code = f"{chair.office_id}:{chair.post_code}"
        if chair.seq == 1:
            r = self._write("POST", f"/mdm/entities/sanctioned-post/{code}/deactivate", {"reason": reason}, reason)
        else:
            r = self._write("PUT", f"/mdm/entities/sanctioned-post/{code}", {"sanctionedCount": chair.seq - 1}, reason)
        if r.status_code >= 400:
            raise ChairError(f"MDM refused to abolish the chair: {r.text[:300]}")
        return SanctionedPostRec(**{**chair.__dict__, "is_active": False})

    def close(self) -> None:
        self._http.close()
