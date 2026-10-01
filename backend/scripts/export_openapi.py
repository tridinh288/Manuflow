"""Print the API's OpenAPI schema; docs/openapi.json holds it (B2: frontend types).

    docker compose exec -T api python scripts/export_openapi.py > docs/openapi.json

The schema is built from the app factory with placeholder settings; no database is
contacted. ``tests/unit/test_openapi_snapshot.py`` fails when the file is stale, and the
frontend generates ``src/api/schema.d.ts`` from it (``npm run gen:api``).
"""

import json
import sys
from typing import Any

from app.core.config import Environment, Settings
from app.main import create_app

PLACEHOLDER_DB = "mysql+pymysql://schema:only@localhost:1/none"


def current_schema() -> dict[str, Any]:
    settings = Settings(
        env=Environment.TEST,
        database_url=PLACEHOLDER_DB,
        migration_database_url=PLACEHOLDER_DB,
        jwt_secret="openapi-export-placeholder-secret-0123456789",  # noqa: S106 - never used to sign
        cors_origins=[],
    )
    return create_app(settings).openapi()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    sys.stdout.write(render(current_schema()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
