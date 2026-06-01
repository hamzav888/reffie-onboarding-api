from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Liveness check endpoint.

    :returns: JSON payload confirming the service is running.
    """
    return HealthResponse(status="ok")
