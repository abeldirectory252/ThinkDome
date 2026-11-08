from sqlalchemy import create_engine, insert, select

from thinkdome.core.orm.orm import Base, Model, StringField


class SchemaCreationRecord(Model):
    value = StringField()


def test_model_metadata_creates_tables_and_generates_ids():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(insert(SchemaCreationRecord._table).values(value="created"))
            record_id = connection.execute(
                select(SchemaCreationRecord._table.c.id)
            ).scalar_one()

        assert record_id
    finally:
        engine.dispose()
