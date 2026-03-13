from pathlib import Path

SQL_DIR = Path(__file__).parent


def load_sql(name: str) -> str:
    path = SQL_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"SQL file not found: {path}")
    return path.read_text(encoding="utf-8")