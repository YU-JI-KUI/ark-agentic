"""
Pytest 配置和 fixtures

处理可选依赖的 mock，确保测试可以在没有完整依赖的情况下运行。
"""

import importlib.util
import sys
import types
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# 将 src 添加到路径
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Mock 可选的重量级依赖（如果未安装）
OPTIONAL_MODULES = [
    "sentence_transformers",
    "jieba",
    "torch",
    "numpy",
]

for module_name in OPTIONAL_MODULES:
    if module_name not in sys.modules:
        try:
            __import__(module_name)
        except ImportError:
            # Use a real ModuleType so Python's import machinery doesn't choke on __spec__
            stub = types.ModuleType(module_name)
            stub.__spec__ = importlib.util.spec_from_loader(module_name, loader=None)
            sys.modules[module_name] = stub


@pytest.fixture
def tmp_sessions_dir(tmp_path: Path) -> Path:
    """Provide a temporary sessions directory for tests requiring SessionManager."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture
def studio_auth_headers():
    """Build Studio bearer auth headers for tests."""
    from ark_agentic.studio.services.authz_service import issue_studio_token

    def _headers(user_id: str = "admin") -> dict[str, str]:
        return {"Authorization": f"Bearer {issue_studio_token(user_id)}"}

    return _headers


@pytest.fixture
def studio_auth_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, studio_auth_headers):
    """Configure isolated Studio auth state for tests."""
    from ark_agentic.studio.services.authz_service import reset_studio_user_store_cache

    def _configure(
        *,
        client=None,
        database_dir: Path | None = None,
        user_id: str = "admin",
    ) -> None:
        db_dir = database_dir or tmp_path
        monkeypatch.setenv("STUDIO_DATABASE_URL", f"sqlite:///{db_dir}/ark_studio.db")
        monkeypatch.setenv("STUDIO_AUTH_TOKEN_SECRET", "test-secret")
        monkeypatch.delenv("STUDIO_AUTH_PROVIDERS", raising=False)
        reset_studio_user_store_cache()
        if client is not None:
            client.headers.update(studio_auth_headers(user_id))

    yield _configure
    reset_studio_user_store_cache()
