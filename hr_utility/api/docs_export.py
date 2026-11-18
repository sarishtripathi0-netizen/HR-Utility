"""Write the API documents: docs/openapi.json, docs/openapi.yaml and docs/swagger.html (spec embedded, opens offline
of this server). The live server serves the same spec at /openapi.json, Swagger UI at /docs and ReDoc at /redoc."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi import FastAPI

SWAGGER_UI = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14"
LOCAL_SERVER = {"url": "http://127.0.0.1:8000", "description": "Local PoC (python run.py)"}

SWAGGER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HR Utility API</title>
<link rel="stylesheet" href="{ui}/swagger-ui.css">
<style>body {{ margin: 0; background: #fafafa; }}</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="{ui}/swagger-ui-bundle.js"></script>
<script>
const spec = {spec};
window.ui = SwaggerUIBundle({{
  spec, dom_id: "#swagger-ui", deepLinking: true, docExpansion: "none", defaultModelsExpandDepth: 0,
  displayRequestDuration: true, filter: true, tryItOutEnabled: true
}});
</script>
</body>
</html>
"""


def document(app: FastAPI, public_url: str | None = None) -> dict:
    """The app's OpenAPI document with the servers a reader can call."""
    spec = dict(app.openapi())
    servers = [LOCAL_SERVER]
    if public_url:
        servers.insert(0, {"url": public_url.rstrip("/"), "description": "This PoC on the network"})
    spec["servers"] = servers
    return spec


def export(app: FastAPI, out_dir: Path, public_url: str | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = document(app, public_url)
    as_json = json.dumps(spec, indent=2, ensure_ascii=False)
    paths = {
        out_dir / "openapi.json": as_json + "\n",
        out_dir / "openapi.yaml": yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120),
        # "</" inside the embedded JSON would close the script element.
        out_dir / "swagger.html": SWAGGER_HTML.format(ui=SWAGGER_UI, spec=as_json.replace("</", "<\\/")),
    }
    for path, text in paths.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    return list(paths)
