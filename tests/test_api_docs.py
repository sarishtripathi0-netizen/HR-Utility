"""The API contract as published: every operation is typed and described, every request body carries an example that
works against the seed (so Swagger's "Try it out" succeeds), and docs/ matches the running app."""
import json
from pathlib import Path

import pytest

from hr_utility.api.docs_export import document

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


@pytest.fixture
def spec(client):
    return client.app.openapi()


def operations(spec):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            yield method.upper(), path, op


def test_every_operation_is_typed_tagged_and_summarised(spec):
    described = {t["name"] for t in spec["tags"] if t.get("description")}
    for method, path, op in operations(spec):
        ok = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in ok, f"{method} {path} has no response model"
        assert op.get("summary"), f"{method} {path} has no summary"
        assert set(op["tags"]) <= described, f"{method} {path} uses an undescribed tag {op['tags']}"


def test_every_request_body_has_an_example(spec):
    schemas = spec["components"]["schemas"]
    for method, path, op in operations(spec):
        body = op.get("requestBody")
        if body:
            name = body["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
            assert schemas[name].get("examples"), f"{method} {path}: {name} has no example"


def test_errors_are_documented_with_the_error_shape(spec):
    for method, path, op in operations(spec):
        if path.startswith("/v1/") and method == "POST" and "/iam/" not in path:
            assert "409" in op["responses"], f"{method} {path} does not document 409 rule refusals"


def test_body_examples_work_against_the_seed(client, spec):
    """Runs every write example in the order a reader would (onboard -> post -> allot -> leave -> end)."""
    ex = {k: v["examples"][0] for k, v in spec["components"]["schemas"].items() if v.get("examples")}

    def ok(method, url, body):
        r = client.request(method, url, json=body)
        assert r.status_code == 200, f"{method} {url}: {r.status_code} {r.text}"
        return r.json()

    assert ok("POST", "/v1/onboarding", ex["OnboardingBody"])["employee_id"].startswith("DEMO-")
    p = ok("POST", "/v1/postings", ex["PostingBody"])
    corrected = ok("POST", f"/v1/postings/{p['id']}/correct", ex["PostingCorrectBody"])  # the new version (BR-10)
    ok("POST", f"/v1/postings/{corrected['id']}/relieve", ex["RelieveBody"])
    a = ok("POST", "/v1/function-allotments", ex["AllotBody"])
    ok("POST", f"/v1/function-allotments/{a['id']}/withdraw", ex["WithdrawBody"])
    v = ok("POST", "/v1/availability", ex["AvailabilityBody"])
    ok("POST", f"/v1/availability/{v['id']}/cancel", ex["ReasonBody"])
    ok("POST", "/v1/posts/DC_NGN-DEALING_ASSISTANT-02/declare-vacant", ex["VacantBody"])
    chair = ok("POST", "/v1/offices/DC_NGN/chairs", ex["ChairCreateBody"])
    ok("POST", f"/v1/posts/{chair['sanctioned_post_id']}/abolish", ex["ReasonBody"])
    ok("PUT", "/v1/employees/EMP-0065", ex["EmployeeCorrectBody"])
    session = ok("POST", "/v1/iam/login", ex["LoginBody"])
    assert ok("POST", "/v1/iam/switch", {**ex["SwitchBody"], "session_id": session["session_id"]})["active_post_id"]


def test_docs_folder_matches_the_app(client):
    """Regenerate with: python run.py --export-openapi docs --no-serve"""
    published = json.loads((DOCS / "openapi.json").read_text(encoding="utf-8"))
    current = document(client.app)
    for key in ("info", "tags", "paths", "components"):
        assert published[key] == current[key], f"docs/openapi.json is out of date ({key}); re-export it"
    assert (DOCS / "openapi.yaml").exists() and "swagger-ui-dist@5" in (DOCS / "swagger.html").read_text(encoding="utf-8")
    for doc in ("api.md", "integration.md"):
        assert (DOCS / doc).exists(), doc
