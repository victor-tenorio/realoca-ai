from alembic import context
from app.config import DATABASE_URL
from app.db import Base, make_engine
import app.models  # register metadata

config = context.config
target_metadata = Base.metadata
url = config.attributes.get("database_url", DATABASE_URL)
if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
