from fastapi import FastAPI

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

app.include_router(router, prefix=settings.api_prefix)
app.include_router(delivery_router, prefix=settings.api_prefix)
app.include_router(job_router, prefix=settings.api_prefix)
