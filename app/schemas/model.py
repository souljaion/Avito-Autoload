from pydantic import BaseModel, Field


class ModelCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    brand: str = ""
    description: str = ""
