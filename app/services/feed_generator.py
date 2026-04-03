import os
from datetime import datetime, timezone

import aiofiles
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.account import Account
from app.models.product import Product
from app.models.feed_export import FeedExport


def _add_element(parent: etree._Element, tag: str, text: str | None, cdata: bool = False):
    if text is None:
        return
    text_str = str(text).strip()
    if text_str == "":
        return
    el = etree.SubElement(parent, tag)
    if cdata:
        el.text = etree.CDATA(text_str)
    else:
        el.text = text_str


def _add_images(ad: etree._Element, images, base_url: str):
    if not images:
        return
    imgs_el = etree.SubElement(ad, "Images")
    sorted_images = sorted(images, key=lambda x: (not x.is_main, x.sort_order))
    for img in sorted_images:
        url = img.url
        if url.startswith("/"):
            url = base_url.rstrip("/") + url
        img_el = etree.SubElement(imgs_el, "Image")
        img_el.set("url", url)


_SHOE_GOODS_TYPES = {"Мужская обувь", "Женская обувь"}

_APPAREL_TYPE_MAP = {
    "Мужская одежда": "Одежда",
    "Женская одежда": "Одежда",
    "Аксессуары": "Аксессуары",
}

# For shoes, ApparelType must be the specific shoe type from Avito's dictionary
# (e.g. "Кроссовки", "Ботинки и полуботинки"), not the generic "Обувь".
# We use goods_subtype which already contains the correct value.


def is_ready_for_feed(product: Product) -> bool:
    """Товар считается готовым к выгрузке, если заполнены все обязательные поля."""
    if product.status != "active":
        return False
    if not product.title or not product.description:
        return False
    if product.price is None:
        return False
    if not product.category or not product.goods_type:
        return False
    if not product.subcategory or not product.goods_subtype:
        return False
    if not product.images:
        return False
    return True


def build_ad_element(product: Product, account: Account, base_url: str) -> etree._Element:
    ad = etree.Element("Ad")

    _add_element(ad, "Id", str(product.id))
    _add_element(ad, "Title", product.title)
    _add_element(ad, "Description", product.description, cdata=True)
    _add_element(ad, "Category", product.category)

    if account.phone:
        _add_element(ad, "ContactPhone", account.phone)
    if account.address:
        _add_element(ad, "Address", account.address)

    extra = product.extra or {}

    _add_element(ad, "GoodsType", product.goods_type)
    if product.goods_type in _SHOE_GOODS_TYPES:
        # For shoes ApparelType = specific shoe type (goods_subtype)
        _add_element(ad, "ApparelType", product.goods_subtype)
    else:
        apparel_type = _APPAREL_TYPE_MAP.get(product.goods_type)
        if apparel_type:
            _add_element(ad, "ApparelType", apparel_type)
    _add_element(ad, "Apparel", product.subcategory)
    _add_element(ad, "GoodsSubType", product.goods_subtype)
    _add_element(ad, "Condition", product.condition)
    _add_element(ad, "AdType", extra.get("ad_type", "Товар приобретён на продажу"))
    _add_element(ad, "Availability", extra.get("availability", "В наличии"))
    _add_element(ad, "Color", product.color)
    _add_element(ad, "Brand", product.brand)

    if product.price is not None:
        _add_element(ad, "Price", str(product.price))

    _add_element(ad, "Size", product.size)
    if product.goods_type not in _SHOE_GOODS_TYPES:
        _add_element(ad, "MaterialsOdezhda", product.material)

    _add_images(ad, product.images, base_url)

    # Delivery
    delivery_val = extra.get("delivery")
    if delivery_val:
        delivery_el = etree.SubElement(ad, "Delivery")
        _add_element(delivery_el, "Option", delivery_val)
    delivery_subsidy_val = extra.get("delivery_subsidy")
    if delivery_subsidy_val:
        _add_element(ad, "DeliverySubsidy", delivery_subsidy_val)

    multi_item_val = extra.get("multi_item")
    if multi_item_val:
        _add_element(ad, "MultiItem", multi_item_val)
    try_on_val = extra.get("try_on")
    if try_on_val:
        _add_element(ad, "TryOn", try_on_val)

    return ad


async def generate_feed(account_id: int, db: AsyncSession) -> tuple[str, int]:
    """Generate XML feed for account. Returns (file_path, products_count)."""
    account = await db.get(Account, account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")

    stmt = (
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.account_id == account_id, Product.status == "active")
        .order_by(Product.id)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    base_url = settings.BASE_URL
    root = etree.Element("Ads", formatVersion="3", target="Avito.ru")

    included = 0
    for product in products:
        if not is_ready_for_feed(product):
            continue
        ad = build_ad_element(product, account, base_url)
        root.append(ad)
        included += 1

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    feeds_dir = settings.FEEDS_DIR
    os.makedirs(feeds_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{account_id}_{timestamp}.xml"
    filepath = os.path.join(feeds_dir, filename)

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(xml_bytes)

    # Also save as latest
    latest_path = os.path.join(feeds_dir, f"{account_id}.xml")
    async with aiofiles.open(latest_path, "wb") as f:
        await f.write(xml_bytes)

    # Record export
    export = FeedExport(
        account_id=account_id,
        file_path=filepath,
        products_count=included,
        status="generated",
    )
    db.add(export)
    await db.commit()

    return filepath, included
