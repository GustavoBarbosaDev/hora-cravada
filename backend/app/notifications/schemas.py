import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class OutboxEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    booking_id: uuid.UUID
    kind: str
    recipient: str
    status: str
    attempts: int
    last_error: str | None
    next_attempt_at: datetime.datetime
    created_at: datetime.datetime
    sent_at: datetime.datetime | None
