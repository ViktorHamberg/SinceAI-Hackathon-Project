"""Local HTTP adapter. Engine preparation occurs only inside the app lifespan."""

import asyncio
import json
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse

from .config import ForecastConfig, HistoryConfig
from .actuals import HistoryUnavailableError, load_actuals
from .forecast_service import ForecastService, prepare_forecast
from .schemas import ForecastResponse, HistoryResponse, OriginsResponse, parse_origin


def create_app(
    config: ForecastConfig | None = None, *,
    service_factory: Callable[[], ForecastService] | None = None,
    history_config: HistoryConfig | None = None,
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
        application.state.actuals_store = None
        application.state.history_cache = {}
        application.state.history_lock = asyncio.Lock()
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
            application.state.actuals_store = None
            application.state.history_cache.clear()

    application = FastAPI(
        title="Finnish imbalance forecast API",
        description="Local historical replay API. Cached validation-origin forecasts; not a live feed.",
        version="1.0", lifespan=lifespan, debug=False, redoc_url=None,
    )
    application.state.forecast_service = None
    application.state.actuals_store = None
    application.state.history_cache = {}

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
        detail = "Historical response is unavailable." if request.url.path == "/api/history" else "Forecast response is unavailable."
        return JSONResponse(status_code=500, content={"detail": detail})

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": "Invalid or missing query parameters."})

    def ready_service(request: Request) -> ForecastService:
        service = request.app.state.forecast_service
        if service is None:
            raise HTTPException(status_code=503, detail="Forecast service is not ready.")
        return service

    @application.get("/api/health", summary="Check forecast readiness")
    async def health(request: Request) -> dict[str, str]:
        if request.query_params:
            raise HTTPException(status_code=400, detail="This endpoint accepts no query parameters.")
        ready_service(request)
        return {"status": "ready"}

    @application.get("/api/origins", response_model=OriginsResponse,
                     summary="List cached historical forecast origins")
    async def get_origins(request: Request):
        if request.query_params:
            raise HTTPException(status_code=400, detail="This endpoint accepts no query parameters.")
        return ready_service(request).origins_response()

    @application.get(
        "/api/forecast", response_model=ForecastResponse,
        summary="Retrieve the cached historical forecast",
        responses={400: {"description": "Invalid origin or unsupported query parameters."},
                   404: {"description": "Origin is not in the prepared selection."},
                   503: {"description": "Forecast service is not ready."},
                   500: {"description": "Forecast response is unavailable."}},
    )
    async def get_forecast(request: Request, origin: str | None = Query(
        default=None, description="Full-hour UTC origin from /api/origins. Omit for the default forecast.",
    )):
        if set(request.query_params) - {"origin"} or len(request.query_params.getlist("origin")) > 1:
            raise HTTPException(status_code=400, detail="Only one origin query parameter is supported.")
        service = ready_service(request)
        if origin is None:
            return service.response()
        try:
            selected = parse_origin(origin)
        except ValueError:
            raise HTTPException(status_code=400, detail="Origin must be a full-hour UTC timestamp.") from None
        try:
            return service.response(selected)
        except KeyError:
            raise HTTPException(status_code=404, detail="Origin is not in the prepared selection.") from None

    @application.get(
        "/api/history", response_model=HistoryResponse,
        summary="Compare one cached forecast with retrospective validation outcomes",
        responses={400: {"description": "One valid UTC origin is required."},
                   404: {"description": "Origin is not in the prepared selection."},
                   500: {"description": "Historical response is unavailable."},
                   503: {"description": "Forecast or validation outcomes unavailable."}},
    )
    async def get_history(request: Request, origin: str = Query(
        description="Required full-hour UTC origin from /api/origins.",
    )):
        if set(request.query_params) != {"origin"} or len(request.query_params.getlist("origin")) != 1:
            raise HTTPException(status_code=400, detail="One origin query parameter is required.")
        service = ready_service(request)
        try:
            selected = parse_origin(origin)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Origin must be a full-hour UTC timestamp.") from None
        try:
            forecast = service.response(selected)
        except KeyError:
            raise HTTPException(status_code=404, detail="Origin is not in the prepared selection.") from None
        async with request.app.state.history_lock:
            if request.app.state.actuals_store is None:
                try:
                    source = history_config if history_config is not None else HistoryConfig.from_data_dir(
                        config.inputs_path.parent if config is not None else None)
                    request.app.state.actuals_store = await asyncio.to_thread(load_actuals, source)
                except (HistoryUnavailableError, ValueError, OSError):
                    raise HTTPException(status_code=503, detail="Historical outcomes are unavailable. Check validation actuals setup.") from None
            cache = request.app.state.history_cache
            if selected not in cache:
                cache[selected] = request.app.state.actuals_store.history_for(forecast).to_json()
            return json.loads(cache[selected])

    generate_openapi = application.openapi

    def history_openapi():
        schema = generate_openapi()
        schema["paths"]["/api/history"]["get"]["responses"].pop("422", None)
        return schema

    application.openapi = history_openapi
    return application


# Creating the app declares HTTP behavior; it does not initialize the engine.
app = create_app()
