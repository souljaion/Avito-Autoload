"""Tests for app.config validators."""

import pytest
from pydantic import ValidationError

from app.config import Settings


# Provide valid non-weak credentials for all tests
_BASE = {
    "SECRET_KEY": "test-secret-key-not-default",
    "BASIC_AUTH_PASSWORD": "strong-test-pass",
}


class TestCrmDsnValidation:
    def test_empty_crm_dsn_allowed(self):
        s = Settings(CRM_DSN="", **_BASE)
        assert s.CRM_DSN == ""

    def test_postgresql_prefix_valid(self):
        s = Settings(CRM_DSN="postgresql://user:pass@localhost/db", **_BASE)
        assert s.CRM_DSN.startswith("postgresql://")

    def test_asyncpg_prefix_valid(self):
        s = Settings(CRM_DSN="postgresql+asyncpg://user:pass@localhost/db", **_BASE)
        assert s.CRM_DSN.startswith("postgresql+asyncpg://")

    def test_mysql_dsn_rejected(self):
        with pytest.raises(ValidationError, match="CRM_DSN must start with"):
            Settings(CRM_DSN="mysql://user:pass@localhost/db", **_BASE)

    def test_random_string_rejected(self):
        with pytest.raises(ValidationError, match="CRM_DSN must start with"):
            Settings(CRM_DSN="not-a-dsn", **_BASE)

    def test_sqlite_rejected(self):
        with pytest.raises(ValidationError, match="CRM_DSN must start with"):
            Settings(CRM_DSN="sqlite:///tmp/test.db", **_BASE)
