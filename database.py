from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./upi.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def migrate_authentication_methods():
    inspector = inspect(engine)
    if "authentication_methods" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("authentication_methods")
    }
    columns_to_add = {
        "credential_reference": "VARCHAR",
        "created_at": "DATETIME",
        "last_used_at": "DATETIME"
    }

    with engine.begin() as connection:
        for column_name, column_type in columns_to_add.items():
            if column_name not in existing_columns:
                connection.execute(text(
                    f"ALTER TABLE authentication_methods ADD COLUMN {column_name} {column_type}"
                ))


def migrate_payment_account_priority():
    inspector = inspect(engine)
    if "payment_accounts" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("payment_accounts")
    }
    if "priority" not in existing_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE payment_accounts ADD COLUMN priority INTEGER NOT NULL DEFAULT 1"
            ))


def migrate_transaction_idempotency_key():
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("transactions")
    }
    if "idempotency_key" not in existing_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE transactions ADD COLUMN idempotency_key VARCHAR"
            ))

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_idempotency_key "
            "ON transactions(idempotency_key) WHERE idempotency_key IS NOT NULL"
        ))


def migrate_transaction_type():
    inspector = inspect(engine)
    if "transactions" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("transactions")
    }
    if "transaction_type" not in existing_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE transactions ADD COLUMN transaction_type VARCHAR NOT NULL DEFAULT 'payment'"
            ))