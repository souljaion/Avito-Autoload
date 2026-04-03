"""Tests for feed_generator: is_ready_for_feed, build_ad_element, ApparelType mapping."""

import os
import types

import pytest
from lxml import etree

from app.services.feed_generator import is_ready_for_feed, build_ad_element


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

    def test_not_active_returns_false(self):
        p = _make_product(status="draft")
        assert is_ready_for_feed(p) is False


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
