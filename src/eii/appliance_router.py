"""Small explicit HTTP router for the offline appliance."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .service import ObservableHandler

RouteHandler = Callable[[ObservableHandler], None]


@dataclass(slots=True)
class ApplianceRouter:
    """Route exact method/path pairs with an optional per-method fallback."""

    routes: dict[tuple[str, str], RouteHandler] = field(default_factory=dict)
    fallbacks: dict[str, RouteHandler] = field(default_factory=dict)

    def add(self, method: str, path: str, handler: RouteHandler) -> None:
        key = (method.upper(), path)
        if key in self.routes:
            raise ValueError(f"duplicate appliance route: {key[0]} {key[1]}")
        self.routes[key] = handler

    def fallback(self, method: str, handler: RouteHandler) -> None:
        normalized = method.upper()
        if normalized in self.fallbacks:
            raise ValueError(f"duplicate appliance fallback: {normalized}")
        self.fallbacks[normalized] = handler

    def dispatch(self, request: ObservableHandler, method: str, path: str) -> None:
        handler = self.routes.get((method.upper(), path)) or self.fallbacks.get(method.upper())
        if handler is None:
            request.send_error(404)
            return
        handler(request)
