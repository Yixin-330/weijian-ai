from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import runpy

from alembic import context
import dotenv


def test_alembic_loads_backend_dotenv_before_resolving_database_url(
    monkeypatch,
) -> None:
    expected_url = "sqlite+pysqlite:///:memory:"
    loaded_paths: list[Path] = []
    configured_options: dict[str, str] = {}

    class FakeConfig:
        config_file_name = None

        def set_main_option(self, name: str, value: str) -> None:
            configured_options[name] = value

        def get_main_option(self, name: str) -> str | None:
            return configured_options.get(name)

    def fake_load_dotenv(path: Path, *, override: bool) -> bool:
        loaded_paths.append(Path(path))
        monkeypatch.setenv("WJ_DATABASE_URL", expected_url)
        return True

    monkeypatch.delenv("WJ_DATABASE_URL", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(context, "config", FakeConfig(), raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(context, "configure", lambda **_: None)
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    monkeypatch.setattr(context, "run_migrations", lambda: None)

    migration_env = Path(__file__).resolve().parents[1] / "migrations" / "env.py"
    runpy.run_path(str(migration_env))

    assert loaded_paths == [Path(__file__).resolve().parents[1] / ".env"]
    assert configured_options["sqlalchemy.url"] == expected_url
