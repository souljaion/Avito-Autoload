from pydantic import BaseModel, Field


class ModelCreateForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    brand: str = ""
    description: str = ""
    category: str = ""
    goods_type: str = ""
    subcategory: str = ""
    goods_subtype: str = ""
    price: int | None = None
