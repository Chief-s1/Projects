from contextlib import contextmanager
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from config import settings

engine = create_engine(
    settings.database_url,
    connect_args={'check_same_thread': False} if settings.database_url.startswith('sqlite') else {},
    pool_pre_ping=True,
)
if settings.database_url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _sqlite_pragmas(dbapi_connection, connection_record):
        cur = dbapi_connection.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA foreign_keys=ON')
        cur.execute('PRAGMA busy_timeout=5000')
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def init_db():
    from database.models import Base
    Base.metadata.create_all(engine)
    # Lightweight migration for databases created by earlier project builds.
    if engine.dialect.name == 'sqlite':
        inspector = inspect(engine)
        cols = {c['name'] for c in inspector.get_columns('tables')}
        if 'starting_chips' not in cols:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE tables ADD COLUMN starting_chips INTEGER NOT NULL DEFAULT 1000'))

