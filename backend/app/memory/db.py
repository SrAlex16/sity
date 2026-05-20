from pathlib import Path
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "app.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


def _configure_sqlite() -> None:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=5000"))
        conn.commit()


def init_db() -> None:
    _configure_sqlite()
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
