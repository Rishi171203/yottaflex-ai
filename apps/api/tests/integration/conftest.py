import os

import pytest

POSTGRES_TEST_DSN = os.environ.get("POSTGRES_TEST_DSN", "")


@pytest.fixture(scope="session")
def postgres_engine():
    from sqlalchemy import create_engine

    dsn = os.environ.get("POSTGRES_TEST_DSN", "")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN not set", allow_module_level=False)
    return create_engine(dsn)
