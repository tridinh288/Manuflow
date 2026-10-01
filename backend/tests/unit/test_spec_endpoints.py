"""B13: the router serves exactly the endpoints of the spec's endpoint table.

The table is parsed from docs/requirements.md itself, so an endpoint the spec lists but
the code lacks (as GET /audit-logs once was) fails here, instead of hiding behind a
hand-copied list.
"""

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

BACKEND_DIR = Path(__file__).resolve().parents[2]
SPEC_CANDIDATES = [BACKEND_DIR.parent / "docs" / "requirements.md", Path("/docs/requirements.md")]
PARAM = re.compile(r"\{[^}]+\}")
CODE = re.compile(r"`([^`]+)`")


def spec_text() -> str:
    for candidate in SPEC_CANDIDATES:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("docs/requirements.md not found")


def endpoint_rows(text: str) -> list[str]:
    section = text[text.index("### Endpoint") :]
    section = section[: section.index("\n\n", section.index("| ---"))]
    return [line.split("|")[1] for line in section.splitlines()[2:] if line.startswith("|")]


def parse(rows: list[str]) -> set[tuple[str, str]]:
    """Expand the table's shorthand: ``GET/POST /x``, a bare ``/sibling`` that reuses the
    previous methods and parent path, and "five similar endpoints for `/a` and `/b`"."""
    endpoints: set[tuple[str, str]] = set()
    products: set[tuple[str, str]] = set()
    for cell in rows:
        if "endpoint tương tự" in cell:  # "Năm endpoint tương tự cho `/materials` và ..."
            for resource in CODE.findall(cell):
                endpoints |= {(m, p.replace("/products", resource, 1)) for m, p in products}
            continue
        methods: list[str] = []
        parent = ""
        for token in CODE.findall(cell):
            if token.startswith("/"):
                path = parent + token
            else:
                verbs, path = token.split(" ", 1)
                methods = verbs.split("/")
            parent = path.rsplit("/", 1)[0]
            for method in methods:
                endpoints.add((method, PARAM.sub("{}", path)))
        if any(path.startswith("/products") for _, path in endpoints):
            products = {
                (m, p) for m, p in endpoints if p.startswith("/products") and p.count("/") <= 2
            }
    return endpoints


def served(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method, PARAM.sub("{}", context.path.removeprefix("/api/v1")))
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute) and context.path.startswith("/api/v1")
        for method in context.methods or ()
    }


# B17 adds the Phase 9 assistant without fixing its paths in the B13 table.
EXTENSIONS = {("GET", "/assistant/status"), ("POST", "/assistant/ask")}


def test_b13_router_serves_exactly_the_spec_endpoint_table(app: FastAPI) -> None:
    spec = parse(endpoint_rows(spec_text())) | EXTENSIONS
    assert len(spec) >= 50  # the parser really read the table
    assert sorted(spec - served(app)) == []  # in the spec, missing in code
    assert sorted(served(app) - spec) == []  # in code, not in the spec


def test_b13_parser_expands_the_table_shorthand() -> None:
    rows = [
        " `GET/POST /users`, `PATCH /users/{id}` ",
        " `GET /products`, `GET /products/{id}` ",
        " `POST /products`, `PUT /products/{id}`, `DELETE /products/{id}` ",
        " Năm endpoint tương tự cho `/materials` ",
        " `POST /orders/{id}/start`, `/cancel` ",
    ]
    assert parse(rows) == {
        ("GET", "/users"),
        ("POST", "/users"),
        ("PATCH", "/users/{}"),
        ("GET", "/products"),
        ("GET", "/products/{}"),
        ("POST", "/products"),
        ("PUT", "/products/{}"),
        ("DELETE", "/products/{}"),
        ("GET", "/materials"),
        ("GET", "/materials/{}"),
        ("POST", "/materials"),
        ("PUT", "/materials/{}"),
        ("DELETE", "/materials/{}"),
        ("POST", "/orders/{}/start"),
        ("POST", "/orders/{}/cancel"),
    }
