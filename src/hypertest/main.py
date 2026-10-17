from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from hypertest.api.delivery_routes import router as delivery_router
from hypertest.api.job_routes import router as job_router
from hypertest.api.routes import router
from hypertest.config import get_settings

settings = get_settings()

app = FastAPI(
    title="HyperTest One",
    version="0.1.0",
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
