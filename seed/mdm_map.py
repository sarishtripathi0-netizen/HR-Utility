"""Mapping rules shared by seed.mdm_load (roster plan -> MDM) and seed.bind (MDM codes -> HR seed)."""
from __future__ import annotations

# Roster-plan post code -> MDM designation code.
DESIGNATION = {"DC": "DISTRICT_COMMISSIONER", "ADC": "ADC", "AC": "ASSISTANT_COMMISSIONER", "CDC": "CO_DISTRICT_COMMISSIONER",
               "CO": "CIRCLE_OFFICER", "SR": "SUB_REGISTRAR", "DAO": "DISTRICT_AGRICULTURE_OFFICER",
               "REG": "REGISTRAR", "PRES": "PRESIDENT"}
# Roster-plan office type -> MDM office type (None = not in MDM yet; kept local).
OFFICE_TYPE = {"DC_OFFICE": "DC_OFFICE", "SUBDIV_OFFICE": "SUBDIV_OFFICE", "CIRCLE_OFFICE": "CIRCLE_OFFICE",
               "DEPT_DISTRICT_OFFICE": "DISTRICT_AGRICULTURE_OFFICE", "DEPT_STATE_OFFICE": None}
# Roster-plan demo function codes that MDM models more finely.
FUNCTION_ALIAS = {"MUTATION_PARTITION": ["MUTATION", "PARTITION"]}
# Posts held only locally until MDM has their office (ACMR waits for MDM's ACR rename).
LOCAL_ONLY_POSTS = ("REG", "PRES")
DEMO_ONLY_CHAIR_SOURCE = "demo (no real allotment)"


def _b(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


def chair_goes_to_mdm(chair: dict) -> bool:
    """Real chairs, and chairs of the real structure filled by demo officers (gap fills, Sub Registrars, the DAO),
    are MDM sanctioned strength. Chairs that exist only to seat demo function holders stay local."""
    if chair["post_code"] in LOCAL_ONLY_POSTS:
        return False
    return not (_b(chair["is_demo"]) and chair["source"].startswith(DEMO_ONLY_CHAIR_SOURCE))
