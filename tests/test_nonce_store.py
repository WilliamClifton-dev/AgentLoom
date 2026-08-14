import hashlib
from pathlib import Path

from sqlalchemy import text

from agentloom.storage import Database, DatabaseNonceStore


def test_database_nonce_store_persists_only_digest_across_instances(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'nonces.db'}")
    database.create_schema()
    first_store = DatabaseNonceStore(database)
    second_store = DatabaseNonceStore(Database(str(database.engine.url)))
    nonce = "nonce-persisted-replay-test"

    assert first_store.consume(nonce)
    assert not second_store.consume(nonce)

    with database.engine.connect() as connection:
        row = connection.execute(
            text("SELECT nonce_digest FROM consumed_grant_nonces")
        ).one()
    assert row.nonce_digest == hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    assert nonce not in row.nonce_digest
