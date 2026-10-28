from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from hypertest.api.archive_routes import router as archive_router
from hypertest.api.cli_authorization_routes import router as cli_authorization_router
from hypertest.api.cloud_routes import router as cloud_router
from hypertest.api.connector_routes import router as connector_router
from hypertest.api.delivery_routes import router as delivery_router
from hypertest.api.harness_routes import router as harness_router
from hypertest.api.input_routes import router as input_router
from hypertest.api.interactive_routes import router as interactive_router
from hypertest.api.issue_executor_routes import router as issue_executor_router
from hypertest.api.job_routes import router as job_router
from hypertest.api.memory_routes import router as memory_router
from hypertest.api.native_routes import router as native_router
from hypertest.api.routes import router
from hypertest.api.source_transfer_routes import router as source_transfer_router
from hypertest.config import get_settings

settings = get_settings()

app = FastAPI(
    title="HyperTest One",
    version="0.2.0",
    description="One Input. One Mission. One Complete Test Cycle.",
)


@app.exception_handler(RequestValidationError)
async def validation_error_response(_request: Request, error: RequestValidationError):
    # Field names and reasons are enough to correct a form. Raw submitted values
    # can include credentials or private PRD text and must not enter error output.
    details = [
        {key: item[key] for key in ("type", "loc", "msg") if key in item}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


app.include_router(router, prefix=settings.api_prefix)
app.include_router(delivery_router, prefix=settings.api_prefix)
app.include_router(job_router, prefix=settings.api_prefix)
app.include_router(input_router, prefix=settings.api_prefix)

app.include_router(harness_router, prefix=settings.api_prefix)

app.include_router(connector_router, prefix=settings.api_prefix)

app.include_router(source_transfer_router,prefix=settings.api_prefix)

app.include_router(issue_executor_router,prefix=settings.api_prefix)

app.include_router(interactive_router, prefix=settings.api_prefix)

app.include_router(native_router, prefix=settings.api_prefix)
app.include_router(cloud_router, prefix=settings.api_prefix)

app.include_router(memory_router, prefix=settings.api_prefix)

app.include_router(cli_authorization_router, prefix=settings.api_prefix)
app.include_router(archive_router, prefix=settings.api_prefix)
