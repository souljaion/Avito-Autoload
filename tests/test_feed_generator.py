"""Tests for feed_generator: is_ready_for_feed, build_ad_element, ApparelType mapping, generate_feed."""

import os
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lxml import etree

from app.services.feed_generator import (
    is_ready_for_feed,
    build_ad_element,
    _add_element,
    _add_images,
)


def _make_image(**kw):
    defaults = {"id": 1, "url": "/media/products/1/img.jpg", "is_main": True, "sort_order": 0}
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


def _make_product(**kw):
    defaults = {
        "id": 1,
        "title": "Nike Air Max 90",
        "description": "Кроссовки Nike",
        "price": 5000,
        "status": "active",
        "category": "Одежда, обувь, аксессуары",
        "goods_type": "Мужская обувь",
        "subcategory": "Кроссовки",
        "goods_subtype": "Кроссовки",
        "condition": "Новое с биркой",
        "brand": "Nike",
        "model": "Air Max 90",
        "color": "Белый",
        "size": "42",
        "material": None,
        "extra": {},
        "images": [_make_image()],
        "image_url": None,
        "use_custom_description": False,
        "avito_id": None,
    }
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


def _make_account(**kw):
    defaults = {
        "id": 1,
        "name": "Test",
        "phone": "+79001234567",
        "address": "Москва",
    }
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


# ── is_ready_for_feed ──


class TestIsReadyForFeed:
    def test_ready_product_returns_true(self):
        p = _make_product()
        assert is_ready_for_feed(p) is True

    def test_no_images_returns_false(self):
        p = _make_product(images=[])
        assert is_ready_for_feed(p) is False

    def test_no_category_returns_false(self):
        p = _make_product(category=None)
        assert is_ready_for_feed(p) is False

    def test_no_goods_type_returns_false(self):
        p = _make_product(goods_type=None)
        assert is_ready_for_feed(p) is False

    def test_no_subcategory_returns_false(self):
        p = _make_product(subcategory=None)
        assert is_ready_for_feed(p) is False

    def test_no_goods_subtype_returns_false(self):
        p = _make_product(goods_subtype=None)
        assert is_ready_for_feed(p) is False

    def test_no_description_returns_false(self):
        p = _make_product(description=None)
        assert is_ready_for_feed(p) is False

    def test_no_price_returns_false(self):
        p = _make_product(price=None)
        assert is_ready_for_feed(p) is False

    def test_draft_with_all_fields_is_ready(self):
        p = _make_product(status="draft")
        assert is_ready_for_feed(p) is True

    def test_scheduled_with_all_fields_is_ready(self):
        p = _make_product(status="scheduled")
        assert is_ready_for_feed(p) is True

    def test_no_description_but_has_template_is_ready(self):
        p = _make_product(description=None)
        p.use_custom_description = False
        assert is_ready_for_feed(p, has_account_template=True) is True

    def test_no_description_custom_mode_not_ready(self):
        p = _make_product(description=None)
        p.use_custom_description = True
        assert is_ready_for_feed(p, has_account_template=True) is False


# ── build_ad_element ──


class TestBuildAdElement:
    def test_mandatory_fields_present(self):
        p = _make_product()
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        xml_str = etree.tostring(ad, encoding="unicode")

        assert ad.find("Id").text == "1"
        assert ad.find("Title").text == "Nike Air Max 90"
        assert ad.find("Category").text == "Одежда, обувь, аксессуары"
        assert ad.find("GoodsType").text == "Мужская обувь"
        assert ad.find("Price").text == "5000"
        assert ad.find("ContactPhone").text == "+79001234567"
        assert ad.find("Address").text == "Москва"

    def test_images_with_base_url(self):
        p = _make_product()
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        images_el = ad.find("Images")
        assert images_el is not None
        img = images_el.find("Image")
        assert img.get("url") == "https://example.com/media/products/1/img.jpg"

    def test_apparel_type_shoes_uses_goods_subtype(self):
        """For shoes, ApparelType should be the specific shoe type (goods_subtype)."""
        p = _make_product(goods_type="Мужская обувь", goods_subtype="Кроссовки")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("ApparelType").text == "Кроссовки"

    def test_apparel_type_shoes_female(self):
        p = _make_product(goods_type="Женская обувь", goods_subtype="Ботинки и полуботинки")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("ApparelType").text == "Ботинки и полуботинки"

    def test_apparel_type_clothing_is_odezhda(self):
        """For clothing, ApparelType should be generic 'Одежда'."""
        p = _make_product(goods_type="Мужская одежда", goods_subtype="Футболки")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("ApparelType").text == "Одежда"

    def test_apparel_type_female_clothing(self):
        p = _make_product(goods_type="Женская одежда", goods_subtype="Платья")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("ApparelType").text == "Одежда"

    def test_apparel_type_accessories(self):
        p = _make_product(goods_type="Аксессуары", goods_subtype="Сумки")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("ApparelType").text == "Аксессуары"

    def test_description_is_cdata(self):
        p = _make_product(description="<b>Test</b> & more")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        xml_str = etree.tostring(ad, encoding="unicode")
        assert "CDATA" in xml_str

    def test_delivery_option(self):
        p = _make_product(extra={"delivery": "Доставка", "ad_type": "Товар приобретён на продажу"})
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        delivery_el = ad.find("Delivery")
        assert delivery_el is not None
        assert delivery_el.find("Option").text == "Доставка"

    def test_avito_id_included_when_set(self):
        p = _make_product(avito_id=123456)
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("AvitoId").text == "123456"

    def test_avito_id_absent_when_none(self):
        p = _make_product(avito_id=None)
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("AvitoId") is None

    def test_no_phone_no_address(self):
        """Account without phone/address should not produce those elements."""
        p = _make_product()
        a = _make_account(phone=None, address=None)
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("ContactPhone") is None
        assert ad.find("Address") is None

    def test_description_override(self):
        """description_override should replace product.description."""
        p = _make_product(description="Original")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com", description_override="Override text")
        assert ad.find("Description").text == "Override text"

    def test_material_shown_for_clothing(self):
        """MaterialsOdezhda should appear for non-shoe goods_type."""
        p = _make_product(goods_type="Мужская одежда", goods_subtype="Футболки", material="Хлопок")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("MaterialsOdezhda").text == "Хлопок"

    def test_material_hidden_for_shoes(self):
        """MaterialsOdezhda should NOT appear for shoes."""
        p = _make_product(goods_type="Мужская обувь", material="Кожа")
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("MaterialsOdezhda") is None

    def test_delivery_subsidy_and_multi_item(self):
        p = _make_product(extra={
            "delivery": "Доставка",
            "delivery_subsidy": "100",
            "multi_item": "Да",
            "try_on": "Нет",
        })
        a = _make_account()
        ad = build_ad_element(p, a, "https://example.com")
        assert ad.find("DeliverySubsidy").text == "100"
        assert ad.find("MultiItem").text == "Да"
        assert ad.find("TryOn").text == "Нет"


# ── _add_element edge cases ──


class TestAddElement:
    def test_none_text_skipped(self):
        parent = etree.Element("Root")
        _add_element(parent, "Tag", None)
        assert len(parent) == 0

    def test_empty_text_skipped(self):
        parent = etree.Element("Root")
        _add_element(parent, "Tag", "   ")
        assert len(parent) == 0

    def test_cdata_wrapping(self):
        parent = etree.Element("Root")
        _add_element(parent, "Desc", "Hello <world>", cdata=True)
        xml_str = etree.tostring(parent, encoding="unicode")
        assert "CDATA" in xml_str


# ── _add_images edge cases ──


class TestAddImages:
    def test_no_images_does_nothing(self):
        ad = etree.Element("Ad")
        _add_images(ad, [], "https://example.com")
        assert ad.find("Images") is None

    def test_images_sorted_main_first(self):
        imgs = [
            _make_image(id=2, is_main=False, sort_order=1, url="/img2.jpg"),
            _make_image(id=1, is_main=True, sort_order=0, url="/img1.jpg"),
        ]
        ad = etree.Element("Ad")
        _add_images(ad, imgs, "https://example.com")
        images_el = ad.find("Images")
        urls = [img.get("url") for img in images_el.findall("Image")]
        assert urls[0] == "https://example.com/img1.jpg"
        assert urls[1] == "https://example.com/img2.jpg"

    def test_max_10_images(self):
        imgs = [_make_image(id=i, is_main=(i == 0), sort_order=i, url=f"/img{i}.jpg") for i in range(15)]
        ad = etree.Element("Ad")
        _add_images(ad, imgs, "https://example.com")
        images_el = ad.find("Images")
        assert len(images_el.findall("Image")) == 10

    def test_absolute_url_not_prefixed(self):
        imgs = [_make_image(url="https://cdn.example.com/photo.jpg")]
        ad = etree.Element("Ad")
        _add_images(ad, imgs, "https://example.com")
        img_el = ad.find("Images").find("Image")
        assert img_el.get("url") == "https://cdn.example.com/photo.jpg"


# ── is_ready_for_feed: imported products ──


class TestIsReadyImported:
    def test_imported_with_avito_id_always_ready(self):
        p = _make_product(status="imported", avito_id=12345, title=None, description=None, price=None, images=[])
        assert is_ready_for_feed(p) is True

    def test_imported_without_avito_id_not_ready(self):
        p = _make_product(status="imported", avito_id=None, title=None)
        assert is_ready_for_feed(p) is False


# ── generate_feed ──


class TestGenerateFeed:
    @pytest.mark.asyncio
    @patch("app.services.feed_generator.aiofiles", new_callable=MagicMock)
    @patch("app.services.feed_generator.os.makedirs")
    @patch("app.services.feed_generator.settings")
    async def test_generate_feed_account_not_found(self, mock_settings, mock_makedirs, mock_aiofiles):
        from app.services.feed_generator import generate_feed

        db = AsyncMock()
        db.get.return_value = None

        with pytest.raises(ValueError, match="Account 99 not found"):
            await generate_feed(99, db)

    @pytest.mark.asyncio
    @patch("app.services.feed_generator.aiofiles")
    @patch("app.services.feed_generator.os.makedirs")
    @patch("app.services.feed_generator.settings")
    async def test_generate_feed_writes_xml_files(self, mock_settings, mock_makedirs, mock_aiofiles):
        """generate_feed should write timestamped and latest XML files."""
        from app.services.feed_generator import generate_feed

        mock_settings.BASE_URL = "https://example.com"
        mock_settings.FEEDS_DIR = "/tmp/test_feeds"

        account = _make_account(id=1, name="TestAcc")

        product = _make_product(
            id=10,
            status="active",
            account_id=1,
            use_custom_description=False,
        )

        db = AsyncMock()
        db.get.return_value = account

        # Mock 4 execute calls:
        # 1) active products query
        # 2) removed products query
        # 3) description template query
        # 4) FeedExport commit
        active_result = MagicMock()
        active_result.scalars.return_value.all.return_value = [product]

        removed_result = MagicMock()
        removed_result.scalars.return_value.all.return_value = []

        tmpl_result = MagicMock()
        tmpl_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [active_result, removed_result, tmpl_result]

        # Mock aiofiles.open as async context manager
        mock_file = AsyncMock()
        mock_aiofiles.open.return_value.__aenter__ = AsyncMock(return_value=mock_file)
        mock_aiofiles.open.return_value.__aexit__ = AsyncMock(return_value=False)

        filepath, count = await generate_feed(1, db)

        assert count == 1
        assert filepath.startswith("/tmp/test_feeds/1_")
        assert filepath.endswith(".xml")
        # Should have written twice (timestamped + latest)
        assert mock_aiofiles.open.call_count == 2
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
