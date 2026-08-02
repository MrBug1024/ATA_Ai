"""Bridge the original domain API routes into the unified FastAPI app."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from . import api as domain_api


def _iter_api_routes(routes):
    """Yield API routes from both flat and FastAPI 0.141 nested router groups."""

    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested_routes = getattr(route, "routes", None)
        if nested_routes is not None:
            yield from _iter_api_routes(nested_routes)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from _iter_api_routes(original_router.routes)


def register_domain_engine(app: FastAPI) -> None:
    """Register every original domain route without changing its public path.

    The old service used a separate ``FastAPI`` object on port 8080. Reusing
    the existing ``APIRoute`` objects keeps request models, response models,
    OpenAPI metadata and endpoint behavior intact while running them in the
    same process as the AI orchestration routes.
    """

    registered_paths = {
        (route.path, tuple(sorted(route.methods or ())))
        for route in _iter_api_routes(app.routes)
    }
    for route in domain_api.app.routes:
        nested_api_routes = list(_iter_api_routes([route]))
        if not nested_api_routes:
            continue
        for api_route in nested_api_routes:
            route_key = (api_route.path, tuple(sorted(api_route.methods or ())))
            if route_key in registered_paths:
                raise RuntimeError(
                    f"Duplicate unified API route: {api_route.path} {api_route.methods}"
                )
            registered_paths.add(route_key)
        app.router.routes.append(route)

    @app.middleware("http")
    async def persist_domain_api_log(request, call_next):
        # All original domain routes live below /api, except its health probe.
        if request.url.path.startswith("/api/") or request.url.path == "/health":
            return await domain_api.log_requests(request, call_next)
        return await call_next(request)
