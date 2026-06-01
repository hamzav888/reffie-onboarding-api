import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChecklistItemUpdate(BaseModel):
    """Partial update payload for a checklist step."""

    done: bool | None = None
    note: str | None = None
    first_touched_at: datetime | None = None
    completed_at: datetime | None = None


class ChecklistItemOut(BaseModel):
    """Output schema for a checklist step."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    step_id: str
    done: bool
    note: str
    first_touched_at: datetime | None
    completed_at: datetime | None
