"""Tests for product creation defaults (Avito params)."""

from app.catalog import (
    DEFAULT_CONDITION, DEFAULT_COLOR,
    DEFAULT_AD_TYPE, DEFAULT_AVAILABILITY, DEFAULT_DELIVERY,
    DEFAULT_DELIVERY_SUBSIDY, DEFAULT_MULTI_ITEM, DEFAULT_TRY_ON,
)


class TestCatalogDefaults:
    """Verify catalog default values match operator requirements."""

    def test_default_color(self):
        assert DEFAULT_COLOR == "Разноцветный"

    def test_default_condition(self):
        assert DEFAULT_CONDITION == "Новое с биркой"

    def test_default_availability(self):
        assert DEFAULT_AVAILABILITY == "В наличии"

    def test_default_delivery(self):
        assert DEFAULT_DELIVERY == "Самовывоз и доставка"

    def test_default_delivery_subsidy(self):
        assert DEFAULT_DELIVERY_SUBSIDY == "Нет скидки"

    def test_default_multi_item(self):
        assert DEFAULT_MULTI_ITEM == "Да"

    def test_default_try_on(self):
        assert DEFAULT_TRY_ON == "Да"
