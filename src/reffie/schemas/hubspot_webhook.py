from pydantic import BaseModel, ConfigDict, Field


class HubSpotWebhookEvent(BaseModel):
    """
    Minimal representation of a single HubSpot webhook event.

    HubSpot sends camelCase keys; ``populate_by_name=True`` allows callers to
    use either the alias or the snake_case field name.
    """

    model_config = ConfigDict(populate_by_name=True)

    event_id: int = Field(alias="eventId")
    subscription_type: str = Field(alias="subscriptionType")
    object_id: int = Field(alias="objectId")
    property_name: str | None = Field(default=None, alias="propertyName")
    property_value: str | None = Field(default=None, alias="propertyValue")
