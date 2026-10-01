"""B16 "Validate": every request body field has an explicit limit.

Scans the request models the router actually uses, so a new endpoint with an unbounded
string or a bare number fails here instead of reaching the database.
"""

import types
from typing import Any, Union, get_args, get_origin

from annotated_types import Ge, Gt, Le, Lt, MaxLen
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from app.main import create_app


def request_models(app: FastAPI) -> set[type[BaseModel]]:
    found: set[type[BaseModel]] = set()
    # FastAPI >= 0.14x nests included routers; iter_route_contexts flattens them.
    for context in iter_route_contexts(app.routes):
        if isinstance(context.original_route, APIRoute):
            for param in context.dependant.body_params:
                annotation = param.field_info.annotation
                if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                    found.add(annotation)
    return found


def _bounded_str(info: FieldInfo, metadata: list[Any]) -> bool:
    for item in metadata:
        if isinstance(item, MaxLen) or getattr(item, "max_length", None) is not None:
            return True
        if getattr(item, "pattern", None):  # anchored patterns with {m,n} only (checked below)
            return "{" in item.pattern and item.pattern.endswith("$")
    return False


def _bounded_number(metadata: list[Any]) -> bool:
    lower = any(isinstance(item, (Ge, Gt)) for item in metadata)
    upper = any(isinstance(item, (Le, Lt)) for item in metadata)
    return lower and upper


def problems(model: type[BaseModel], seen: set[type[BaseModel]]) -> list[str]:
    if model in seen:
        return []
    seen.add(model)
    found: list[str] = []
    for name, info in model.model_fields.items():
        found += _check(
            f"{model.__name__}.{name}", info.annotation, info, list(info.metadata), seen
        )
    return found


def _check(
    where: str, annotation: Any, info: FieldInfo, metadata: list[Any], seen: set[type[BaseModel]]
) -> list[str]:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return [
            problem
            for arg in get_args(annotation)
            if arg is not type(None)
            for problem in _check(where, arg, info, metadata, seen)
        ]
    if origin is list:
        (item,) = get_args(annotation)
        has_cap = any(isinstance(m, MaxLen) for m in metadata)
        found = [] if has_cap else [f"{where}: list without max_length"]
        return found + _check(f"{where}[]", item, info, [], seen)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return problems(annotation, seen)
    if annotation is str:
        return [] if _bounded_str(info, metadata) else [f"{where}: str without a length limit"]
    if annotation is int:
        return [] if _bounded_number(metadata) else [f"{where}: int without lower+upper bound"]
    if annotation is float:
        return [f"{where}: float (quantities are Decimal strings)"]
    return []  # bool, enums, Literal, datetime, SecretStr-free types


def test_b16_every_request_field_has_an_explicit_limit() -> None:
    seen: set[type[BaseModel]] = set()
    app = create_app()
    assert len(request_models(app)) >= 15  # the scan really sees the API
    found = [
        p
        for model in sorted(request_models(app), key=lambda m: m.__name__)
        for p in problems(model, seen)
    ]
    assert found == []


def test_b16_scan_flags_unbounded_fields() -> None:
    class Loose(BaseModel):
        note: str
        count: int
        ratio: float
        tags: list[str]

    assert problems(Loose, set()) == [
        "Loose.note: str without a length limit",
        "Loose.count: int without lower+upper bound",
        "Loose.ratio: float (quantities are Decimal strings)",
        "Loose.tags: list without max_length",
        "Loose.tags[]: str without a length limit",
    ]


def test_b16_request_models_reject_unknown_fields() -> None:
    """Untrusted input: a client cannot smuggle status, role or computed totals."""
    seen: set[type[BaseModel]] = set()
    for model in request_models(create_app()):
        problems(model, seen)  # collects nested models too
    lenient = sorted(m.__name__ for m in seen if m.model_config.get("extra") != "forbid")
    assert lenient == []
