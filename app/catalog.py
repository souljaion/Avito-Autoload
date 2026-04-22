"""
Local catalog of Avito categories for clothing/footwear.

4-level hierarchy matching Avito XML structure:
  Category → GoodsType → Apparel → GoodsSubType

DB field mapping:
  product.category      → <Category>
  product.goods_type    → <GoodsType>
  product.subcategory   → <Apparel>       (column reused)
  product.goods_subtype → <GoodsSubType>
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.avito_category import AvitoCategory

# ── Hardcoded fallback values (4-level hierarchy) ─────────────────

CATEGORIES = [
    "Одежда, обувь, аксессуары",
]

# Category → GoodsType
GOODS_TYPES = {
    "Одежда, обувь, аксессуары": [
        "Женская одежда",
        "Женская обувь",
        "Мужская одежда",
        "Мужская обувь",
        "Аксессуары",
    ],
}

# GoodsType → Apparel
APPARELS = {
    "Мужская одежда": [
        "Брюки", "Верхняя одежда", "Джинсы", "Кофты и футболки",
        "Пиджаки и костюмы", "Рубашки", "Спортивные костюмы", "Шорты",
    ],
    "Женская одежда": [
        "Блузки и рубашки", "Брюки", "Верхняя одежда", "Джинсы",
        "Кофты и футболки", "Платья", "Спортивные костюмы", "Юбки", "Шорты",
    ],
    "Мужская обувь": [
        "Ботинки и сапоги", "Кроссовки и кеды", "Сандалии и шлёпанцы", "Туфли",
    ],
    "Женская обувь": [
        "Босоножки и сандалии", "Ботинки и сапоги", "Кроссовки и кеды", "Туфли",
    ],
    "Аксессуары": [
        "Кошельки", "Очки", "Ремни", "Сумки", "Часы",
    ],
}

# Apparel → GoodsSubType
GOODS_SUBTYPES = {
    "Кофты и футболки": [
        "Водолазка", "Кардиган", "Лонгслив", "Поло",
        "Свитер", "Свитшот", "Футболка", "Худи",
    ],
    "Верхняя одежда": [
        "Ветровка", "Джинсовка", "Дублёнка", "Куртка",
        "Пальто", "Парка", "Пуховик", "Шуба",
    ],
    "Брюки": ["Брюки", "Джоггеры", "Леггинсы", "Чинос"],
    "Рубашки": ["Рубашка", "Рубашка джинсовая"],
    "Блузки и рубашки": ["Блузка", "Рубашка", "Топ"],
    "Платья": ["Платье"],
    "Юбки": ["Юбка"],
    "Шорты": ["Шорты"],
    "Джинсы": ["Джинсы"],
    "Кроссовки и кеды": ["Кеды", "Кроссовки"],
    "Ботинки и сапоги": ["Ботинки", "Сапоги", "Челси"],
    "Туфли": ["Лоферы", "Мокасины", "Оксфорды", "Туфли"],
    "Сандалии и шлёпанцы": ["Сандалии", "Шлёпанцы"],
    "Босоножки и сандалии": ["Босоножки", "Сандалии"],
    "Сумки": ["Клатч", "Поясная сумка", "Рюкзак", "Сумка"],
}

CONDITIONS = [
    "Новое с биркой",
]

DEFAULT_CONDITION = "Новое с биркой"
DEFAULT_COLOR = "Разноцветный"

AD_TYPES = ["Товар приобретён на продажу", "Товар от производителя"]
DEFAULT_AD_TYPE = "Товар приобретён на продажу"

AVAILABILITIES = ["В наличии", "Под заказ"]
DEFAULT_AVAILABILITY = "В наличии"

DELIVERY_OPTIONS = ["Самовывоз", "Доставка", "Самовывоз и доставка"]
DEFAULT_DELIVERY = "Самовывоз и доставка"

DELIVERY_SUBSIDIES = ["Нет скидки", "50%", "100%"]
DEFAULT_DELIVERY_SUBSIDY = "Нет скидки"

MULTI_ITEM_OPTIONS = ["Нет", "Да"]
DEFAULT_MULTI_ITEM = "Да"

TRY_ON_OPTIONS = ["Нет", "Да"]
DEFAULT_TRY_ON = "Да"

_FALLBACK = {
    "categories": CATEGORIES,
    "goods_types": GOODS_TYPES,
    "apparels": APPARELS,
    "goods_subtypes": GOODS_SUBTYPES,
    "conditions": CONDITIONS,
    "default_condition": DEFAULT_CONDITION,
    "catalog_source": "fallback",
}

# ── Subtype availability (updated by get_catalog) ───────────────
# Set of subcategory names that have at least one goods_subtype child.
# Initialized from hardcoded fallback, refreshed each time get_catalog()
# loads from the DB.
_subcategories_with_subtypes: set[str] = set(GOODS_SUBTYPES.keys())


def requires_subtype(category: str | None, goods_type: str | None, subcategory: str | None) -> bool:
    """True if this taxonomy combo has subtypes in avito_categories.

    Returns False if any arg is None/empty — incomplete taxonomy can't
    require a subtype.
    """
    if not category or not goods_type or not subcategory:
        return False
    return subcategory in _subcategories_with_subtypes


# ── DB-backed getter (with fallback) ──────────────────────────────

async def get_catalog(db: AsyncSession) -> dict:
    """Return full catalog dict for the product form.

    Queries the avito_categories tree for the 4-level hierarchy:
      Category → GoodsType → Apparel → GoodsSubType
    Falls back to hardcoded constants if the DB tree is empty.
    """
    # Find "Одежда, обувь, аксессуары" node that is a child of a top-level parent
    root_result = await db.execute(
        select(AvitoCategory).where(
            AvitoCategory.name == "Одежда, обувь, аксессуары",
            AvitoCategory.parent_id == 8705,
        )
    )
    root = root_result.scalar_one_or_none()
    if not root:
        return _FALLBACK

    # Load all descendants in one query (3 levels deep)
    all_result = await db.execute(select(AvitoCategory))
    all_cats = {c.id: c for c in all_result.scalars().all()}

    # Build children index
    children: dict[int, list[AvitoCategory]] = defaultdict(list)
    for c in all_cats.values():
        if c.parent_id is not None:
            children[c.parent_id].append(c)
    for lst in children.values():
        lst.sort(key=lambda c: c.name)

    # Level 1: GoodsType (children of root)
    goods_type_nodes = children.get(root.id, [])
    if not goods_type_nodes:
        return _FALLBACK

    categories = [root.name]
    goods_types = {root.name: [gt.name for gt in goods_type_nodes]}
    apparels: dict[str, list[str]] = {}
    goods_subtypes: dict[str, list[str]] = {}

    for gt_node in goods_type_nodes:
        # Level 2: Apparel (children of GoodsType)
        apparel_nodes = children.get(gt_node.id, [])
        apparels[gt_node.name] = [a.name for a in apparel_nodes]

        for ap_node in apparel_nodes:
            # Level 3: GoodsSubType (children of Apparel)
            subtype_nodes = children.get(ap_node.id, [])
            if subtype_nodes:
                goods_subtypes[ap_node.name] = [s.name for s in subtype_nodes]

    # Refresh the module-level subtype availability set
    global _subcategories_with_subtypes
    _subcategories_with_subtypes = set(goods_subtypes.keys())

    return {
        "categories": categories,
        "goods_types": goods_types,
        "apparels": apparels,
        "goods_subtypes": goods_subtypes,
        "conditions": CONDITIONS,
        "default_condition": DEFAULT_CONDITION,
        "catalog_source": "database",
    }


# ── Helpers for fields_data extraction (for future use) ───────────

def _extract_select_values(fields_data: dict, tag: str) -> list[str]:
    """Extract allowed values for a select-type field from cached API response."""
    if not fields_data or fields_data.get("_unavailable"):
        return []
    fields = fields_data.get("fields") or []
    for field in fields:
        if field.get("tag") != tag:
            continue
        contents = field.get("content") or []
        for content in contents:
            if content.get("field_type") != "select":
                continue
            raw_values = content.get("values") or []
            values = []
            for v in raw_values:
                name = v.get("value") or v.get("name") or ""
                if name:
                    values.append(name)
            if values:
                return values
    return []
