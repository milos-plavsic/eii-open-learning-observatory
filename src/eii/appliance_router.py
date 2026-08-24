"""Small explicit HTTP router for the offline appliance."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from .service import ObservableHandler

RouteHandler = Callable[[ObservableHandler], None]
_PARAMETER = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)(?::(path))?\}$")


@dataclass(frozen=True, slots=True)
class PatternRoute:
    method: str
    template: str
    expression: re.Pattern[str]
    shape: tuple[str, ...]
    specificity: tuple[int, int]
    handler: RouteHandler


def _segment_intersects(left: str, right: str) -> bool:
    """Return whether two non-path segment tokens share at least one value."""
    if left == "{segment}":
        return right == "{segment}" or bool(right)
    if right == "{segment}":
        return bool(left)
    return left == right


def patterns_intersect(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """Decide intersection for literals, one-segment wildcards and terminal paths."""
    left_path = left.index("{path}") if "{path}" in left else None
    right_path = right.index("{path}") if "{path}" in right else None
    left_fixed = len(left) if left_path is None else left_path
    right_fixed = len(right) if right_path is None else right_path
    common = min(left_fixed, right_fixed)
    if any(not _segment_intersects(left[index], right[index]) for index in range(common)):
        return False
    if left_path is None and right_path is None:
        return len(left) == len(right)
    if left_path is not None and right_path is None:
        return len(right) >= left_path
    if left_path is None:
        return len(left) >= cast(int, right_path)
    return True


def compile_path_pattern(template: str) -> tuple[re.Pattern[str], tuple[str, ...], tuple[int, int]]:
    """Compile a bounded segment pattern without permitting arbitrary regex."""
    if not template.startswith("/") or "?" in template or "#" in template:
        raise ValueError("appliance route pattern must be an absolute URL path")
    parts = template.split("/")[1:]
    names: set[str] = set()
    expressions = []
    shape = []
    static_segments = 0
    for index, part in enumerate(parts):
        match = _PARAMETER.fullmatch(part)
        if match:
            name, converter = match.groups()
            if name in names:
                raise ValueError(f"duplicate appliance route parameter: {name}")
            names.add(name)
            if converter == "path":
                if index != len(parts) - 1:
                    raise ValueError("path route parameter must be the final segment")
                expressions.append(f"(?P<{name}>.*)")
                shape.append("{path}")
            else:
                expressions.append(f"(?P<{name}>[^/]+)")
                shape.append("{segment}")
        else:
            if "{" in part or "}" in part:
                raise ValueError(f"invalid appliance route pattern segment: {part}")
            expressions.append(re.escape(part))
            shape.append(part)
            static_segments += 1
    expression = re.compile("^/" + "/".join(expressions) + "$")
    return expression, tuple(shape), (static_segments, len(parts))


@dataclass(slots=True)
class ApplianceRouter:
    """Route exact paths first, then deterministic bounded path patterns."""

    routes: dict[tuple[str, str], RouteHandler] = field(default_factory=dict)
    patterns: list[PatternRoute] = field(default_factory=list)

    def add(self, method: str, path: str, handler: RouteHandler) -> None:
        if "{" in path or "}" in path:
            self.add_pattern(method, path, handler)
            return
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("appliance route must be an absolute URL path")
        key = (method.upper(), path)
        if key in self.routes:
            raise ValueError(f"duplicate appliance route: {key[0]} {key[1]}")
        self.routes[key] = handler

    def add_pattern(self, method: str, template: str, handler: RouteHandler) -> None:
        normalized = method.upper()
        expression, shape, specificity = compile_path_pattern(template)
        if any(
            route.method == normalized
            and route.specificity == specificity
            and patterns_intersect(route.shape, shape)
            for route in self.patterns
        ):
            raise ValueError(
                f"equal-precedence appliance route patterns overlap: {normalized} {template}"
            )
        self.patterns.append(
            PatternRoute(normalized, template, expression, shape, specificity, handler)
        )
        self.patterns.sort(key=lambda route: (route.specificity, route.template), reverse=True)

    def dispatch(self, request: ObservableHandler, method: str, path: str) -> None:
        normalized = method.upper()
        if handler := self.routes.get((normalized, path)):
            cast(Any, request).route_params = {}
            handler(request)
            return
        for route in self.patterns:
            if route.method == normalized and (match := route.expression.fullmatch(path)):
                cast(Any, request).route_params = match.groupdict()
                route.handler(request)
                return
        request.send_error(404)
