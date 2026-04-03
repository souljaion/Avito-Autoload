from pydantic import BaseModel, Field


class ProductCreateForm(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    sku: str = Field("", max_length=100)
    brand: str = Field("", max_length=255)
    model: str = Field("", max_length=255)
    category: str = ""
    goods_type: str = ""
    subcategory: str = ""
    goods_subtype: str = ""
    size: str = ""
    color: str = ""
    material: str = ""
    condition: str = ""
    price: str = "0"
    description: str = Field("", max_length=3000)
    status: str = "draft"
    account_id: str = ""
    ad_type: str = ""
    availability: str = ""
    delivery: str = ""
    delivery_subsidy: str = ""
    multi_item: str = ""
    try_on: str = ""
    model_id: str = ""
    pack_id: str = ""
    pack_uniquify: str = ""

    def validated_price(self) -> int | None:
        try:
            val = int(self.price) if self.price and self.price.strip() else None
        except (ValueError, TypeError):
            val = None
        return val
