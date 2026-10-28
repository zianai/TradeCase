"""Read-only integrity verification for every persisted object reference."""

import json

from tradecase.platform.config import Settings
from tradecase.platform.db import Database
from tradecase.platform.maintenance import verify_object_references
from tradecase.platform.storage import configured_storage


def verify(db, storage):
    return verify_object_references(db, storage)


if __name__ == "__main__":
    settings = Settings()
    database = Database(settings.database_url)
    try:
        result = verify(database, configured_storage(settings))
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(bool(result["errors"]))
    finally:
        database.close()
