"""Local HTTP adapter. Engine preparation occurs only inside the app lifespan."""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse

from .config import ForecastConfig
from .forecast_service import ForecastService, prepare_forecast
from .schemas import ForecastResponse


def create_app(
    config: ForecastConfig | None = None, *,
    service_factory: Callable[[], ForecastService] | None = None,
) -> FastAPI:
    """Compose an independent app without loading data or preparing a model.

    service_factory is a local composition/test seam, never client-supplied input.
    Normal execution always uses the genuine Step 1A service. Multiple independent
    app instances own independent snapshots; no module-global fitted state is used.
    """
    if config is not None and service_factory is not None:
        raise ValueError("Choose explicit configuration or a service factory, not both.")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.forecast_service = None
        try:
            # Fitting is synchronous and CPU-heavy. Keep it off the event loop;
            # the ASGI server does not accept requests until startup finishes.
            factory = service_factory if service_factory is not None else lambda: prepare_forecast(config)
            service = await asyncio.to_thread(factory)
            if not isinstance(service, ForecastService):
                raise TypeError("Forecast preparation must return ForecastService.")
        except Exception:
            # Uvicorn logs lifespan exceptions. Expose only this fixed diagnostic,
            # never chained input/model errors, private paths or source values.
            raise RuntimeError(
                "Forecast service could not start. Check private input setup and backend/README.md."
            ) from None
        application.state.forecast_service = service
        try:
            yield
        finally:
            application.state.forecast_service = None

    application = FastAPI(
        title="Finnish imbalance forecast API",
        description="Local historical replay API. One cached validation-origin forecast; not a live feed.",
        version="1.0", lifespan=lifespan, debug=False, redoc_url=None,
    )
    application.state.forecast_service = None

    @application.middleware("http")
    async def safe_response(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            # Catch before server middleware can log arbitrary retrieval errors.
            response = JSONResponse(status_code=500, content={"detail": "Request could not be completed."})
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(ResponseValidationError)
    async def invalid_response(request: Request, error: ResponseValidationError):
        # Validation exceptions can contain the offending response. Do not echo/log it.
        return JSONResponse(status_code=500, content={"detail": "Forecast response is unavailable."})

    def ready_service(request: Request) -> ForecastService:
        if request.query_params:
            raise HTTPException(status_code=400, detail="This endpoint accepts no query parameters.")
        service = request.app.state.forecast_service
        if service is None:
            raise HTTPException(status_code=503, detail="Forecast service is not ready.")
        return service

    @application.get("/api/health", summary="Check forecast readiness")
    async def health(request: Request) -> dict[str, str]:
        ready_service(request)
        return {"status": "ready"}

    @application.get(
        "/api/forecast", response_model=ForecastResponse,
        summary="Retrieve the cached historical forecast",
        responses={400: {"description": "Query parameters are not supported yet."},
                   503: {"description": "Forecast service is not ready."},
                   500: {"description": "Forecast response is unavailable."}},
    )
    async def get_forecast(request: Request):
        return ready_service(request).response()

    return application


# Creating the app declares HTTP behavior; it does not initialize the engine.
app = create_app()
