import uuid

from pydantic import BaseModel, ConfigDict


class PocIn(BaseModel):
    """Input schema for creating a point of contact."""

    name: str
    email: str
    phone: str | None = None
    role: str | None = None


class PocOut(BaseModel):
    """Output schema for a point of contact."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    name: str
    email: str
    phone: str | None
    role: str | None
