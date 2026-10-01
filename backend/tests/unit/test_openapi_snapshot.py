"""docs/openapi.json is what the frontend's types are generated from (B2, B17); it must
match the API exactly, or the frontend would be type-checked against a stale contract."""

import importlib.util
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
SNAPSHOTS = [BACKEND_DIR.parent / "docs" / "openapi.json", Path("/docs/openapi.json")]


def test_b17_openapi_snapshot_matches_the_api() -> None:
    spec = importlib.util.spec_from_file_location(
        "export_openapi", BACKEND_DIR / "scripts" / "export_openapi.py"
    )
    assert spec and spec.loader
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)

    snapshot = next(path for path in SNAPSHOTS if path.is_file())
    expected = exporter.render(exporter.current_schema())
    assert snapshot.read_text(encoding="utf-8") == expected, (
        "docs/openapi.json is stale. Run `docker compose exec -T api python "
        "scripts/export_openapi.py > docs/openapi.json`, then `npm run gen:api` in frontend/"
    )
