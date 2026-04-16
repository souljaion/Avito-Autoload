"""Tests for app/utils/title_heuristic.guess_goods_type."""

import pytest

from app.utils.title_heuristic import guess_goods_type


class TestShoes:
    @pytest.mark.parametrize("title", [
        "Кроссовки Nike Air Max 90 мужские",
        "Adidas Sneakers Mens 42",
        "Кроссовки Asics для men",
        "On Cloudmonster men's runners",
    ])
    def test_men_shoes(self, title):
        assert guess_goods_type(title) == "Мужская обувь"

    @pytest.mark.parametrize("title", [
        "Кроссовки Nike Air Max 90 женские",
        "Adidas Sneakers Womens 38",
        "Кроссовки Asics женский размер",
        "Балетки кожаные",
        "Мюли черные",
    ])
    def test_women_shoes(self, title):
        assert guess_goods_type(title) == "Женская обувь"

    @pytest.mark.parametrize("title", [
        "Кроссовки Nike Air Max 90",
        "Adidas Sneakers retro",
        "Кроссовки New Balance",
        "Boots Dr Martens",
    ])
    def test_unisex_shoes(self, title):
        assert guess_goods_type(title) == "Обувь"

    def test_no_shoe_keyword_returns_none(self):
        """Conservative: no explicit shoe noun → no guess."""
        assert guess_goods_type("Nike Air Max 90") is None
        assert guess_goods_type("Yeezy 350 Boost") is None


class TestApparel:
    @pytest.mark.parametrize("title", [
        "Nike мужская футболка",
        "Hoodie Carhartt mens",
        "Свитшот Stussy для men",
    ])
    def test_men_apparel(self, title):
        assert guess_goods_type(title) == "Мужская одежда"

    @pytest.mark.parametrize("title", [
        "Платье Mango",
        "Юбка джинсовая",
        "Худи Stussy женское",
        "Sweatshirt Champion womens",
    ])
    def test_women_apparel(self, title):
        assert guess_goods_type(title) == "Женская одежда"

    @pytest.mark.parametrize("title", [
        "Stussy Hoodie black",
        "Carhartt футболка чёрная",
        "Свитшот Cav Empt",
    ])
    def test_unisex_apparel(self, title):
        assert guess_goods_type(title) == "Одежда"


class TestAccessories:
    @pytest.mark.parametrize("title", [
        "Сумка Prada винтаж",
        "Backpack Carhartt WIP",
        "Кепка New Era",
        "Шапка Stone Island",
    ])
    def test_accessories(self, title):
        assert guess_goods_type(title) == "Аксессуары"


class TestNoMatch:
    @pytest.mark.parametrize("title", [
        None,
        "",
        "   ",
        "Стол письменный IKEA",
        "iPhone 15 Pro Max",
        "Велосипед горный",
    ])
    def test_returns_none(self, title):
        assert guess_goods_type(title) is None


class TestGenderDisambiguation:
    def test_both_markers_falls_back_to_unisex(self):
        # Both "men" and "women" present → can't decide → unisex
        assert guess_goods_type("Кроссовки men women all sizes") == "Обувь"

    def test_case_insensitive(self):
        assert guess_goods_type("NIKE КРОССОВКИ МУЖСКИЕ") == "Мужская обувь"
        assert guess_goods_type("nike sneakers MENS") == "Мужская обувь"
