"""Heuristic goods_type guesser for imported product titles.

Looks for footwear/apparel keywords in the title (case-insensitive) and tries
to disambiguate gender. Returns None if nothing matches confidently — the
caller should fall back to manual entry rather than store a wrong value.
"""

import re

# ── Gender markers ──
_MEN_MARKERS = (
    "мужск", "мужс", "мужчин",
    " men", " mens", " man", "men's",
)
_WOMEN_MARKERS = (
    "женск", "женс", "женщин",
    " women", " womens", " woman", "women's",
    "wmns",
)

# ── Keyword groups ──
_SHOES_GENERIC = (
    "кроссовки", "кроссовок", "кросcовки",
    "кеды", "ботинки", "сапоги", "сапог",
    "мокасины", "лоферы", "слипоны",
    "sneakers", "boots", "shoes", "trainers", "runners",
)
_SHOES_MEN_ONLY = ("ботинок",)  # rare; "ботинок" tends to be men's
_SHOES_WOMEN_ONLY = ("мюли", "балетки", "босоножки", "туфли")

_APPAREL_GENERIC = (
    "футболка", "футболку", "футболки",
    "худи", "толстовка", "толстовку",
    "джинсы", "джинс",
    "брюки", "брюк",
    "куртка", "куртку",
    "пуховик", "пуховика",
    "свитшот", "свитер", "кардиган", "поло",
    "tee", "hoodie", "sweatshirt", "jeans", "jacket", "coat",
)
_APPAREL_WOMEN_ONLY = ("платье", "юбка", "юбку", "блузка", "блузку", "сарафан")

_ACCESSORY_KEYWORDS = (
    "сумка", "сумку", "рюкзак", "ремень", "кошелёк", "кошелек",
    "очки", "часы", "шапка", "кепка", "бейсболка", "перчатки", "шарф",
    "bag", "backpack", "belt", "wallet", "cap", "hat", "scarf", "watch",
)


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    for n in needles:
        # Single-word/substring check; for English markers we kept the leading
        # space so " men" doesn't false-match "women".
        if n in text:
            return True
    return False


def _detect_gender(text: str) -> str | None:
    """Return 'men', 'women' or None — the more-specific marker wins."""
    has_women = _has_any(text, _WOMEN_MARKERS)
    has_men = _has_any(text, _MEN_MARKERS)
    if has_women and not has_men:
        return "women"
    if has_men and not has_women:
        return "men"
    return None


def guess_goods_type(title: str | None) -> str | None:
    """Map a product title to a goods_type Avito accepts.

    Returns one of the following or None:
      "Мужская обувь", "Женская обувь", "Обувь",
      "Мужская одежда", "Женская одежда", "Одежда",
      "Аксессуары"
    """
    if not title:
        return None

    # Normalize: lowercase + collapse whitespace + pad with spaces so word-boundary
    # markers like " men" can match at start/end as well.
    text = " " + re.sub(r"\s+", " ", title).strip().lower() + " "

    gender = _detect_gender(text)

    # Footwear has highest specificity — check first
    if _has_any(text, _SHOES_WOMEN_ONLY):
        return "Женская обувь"
    if _has_any(text, _SHOES_MEN_ONLY):
        return "Мужская обувь"
    if _has_any(text, _SHOES_GENERIC):
        if gender == "men":
            return "Мужская обувь"
        if gender == "women":
            return "Женская обувь"
        return "Обувь"

    if _has_any(text, _APPAREL_WOMEN_ONLY):
        return "Женская одежда"
    if _has_any(text, _APPAREL_GENERIC):
        if gender == "men":
            return "Мужская одежда"
        if gender == "women":
            return "Женская одежда"
        return "Одежда"

    if _has_any(text, _ACCESSORY_KEYWORDS):
        return "Аксессуары"

    return None
