import sqlite3
from pathlib import Path

import pytest

from fpl_model.storage.db import apply_schema


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    apply_schema(connection)
    yield connection
    connection.close()
