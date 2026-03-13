from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str = "public"

    @property
    def sqlalchemy_url(self) -> str:
        # psycopg3 driver
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class Settings:
    postgres: PostgresConfig
    nh3_ppm_max: float = 1000.0  # ajuste se o sensor for 0..500, 0..2000 etc.
    td_days_default: int = 365 * 2  # vida nominal default (ex.: 2 anos); ajuste por modelo

    @staticmethod
    def load(path: str | Path | None = None) -> "Settings":
        if path is None:
            path = Path(__file__).resolve().parents[2] / "config" / "db.yaml"
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Arquivo de config não encontrado: {path}. "
                f"Crie a partir de config/db.yaml.example"
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        pg = raw.get("postgres", {})
        return Settings(
            postgres=PostgresConfig(
                host=str(pg["host"]),
                port=int(pg.get("port", 5432)),
                database=str(pg["database"]),
                user=str(pg["user"]),
                password=str(pg["password"]),
                schema=str(pg.get("schema", "public")),
            ),
            nh3_ppm_max=float(raw.get("nh3_ppm_max", 1000.0)),
            td_days_default=int(raw.get("td_days_default", 365 * 2)),
        )
