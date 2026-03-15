"""
Pytest 配置和 fixtures

处理可选依赖的 mock，确保测试可以在没有完整依赖的情况下运行。
"""

import sys
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
            sys.modules[module_name] = MagicMock()


@pytest.fixture
def tmp_sessions_dir(tmp_path: Path) -> Path:
    """Provide a temporary sessions directory for tests requiring SessionManager."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d
