"""
Mock 数据加载器

从 JSON 文件加载业务接口返回数据，支持多场景测试。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MockDataLoader:
    """Mock 数据加载器"""
    
    def __init__(self, mock_data_dir: str | Path | None = None):
        if mock_data_dir is None:
            # 默认使用 agents/securities/mock_data
            mock_data_dir = Path(__file__).parent.parent / "mock_data"
        
        self.mock_data_dir = Path(mock_data_dir)
        if not self.mock_data_dir.exists():
            logger.warning(f"Mock data directory not found: {self.mock_data_dir}")
            self.mock_data_dir.mkdir(parents=True, exist_ok=True)
    
    def load(
        self,
        service_name: str,
        scenario: str = "default",
        **params: Any,
    ) -> dict[str, Any]:
        """加载 Mock 数据
        
        Args:
            service_name: 服务名称（如 account_overview）
            scenario: 场景名称（如 normal_user, margin_user）
            **params: 额外参数（如 security_code）
        
        Returns:
            Mock 数据字典
        """
        service_dir = self.mock_data_dir / service_name
        
        # 1. 尝试根据参数查找特定文件
        if "security_code" in params:
            # 例如：security_detail/stock_510300.json
            specific_file = service_dir / f"stock_{params['security_code']}.json"
            if specific_file.exists():
                return self._load_json(specific_file)
        
        # 2. 尝试加载场景文件
        scenario_file = service_dir / f"{scenario}.json"
        if scenario_file.exists():
            return self._load_json(scenario_file)
        
        # 3. 尝试加载默认文件
        default_file = service_dir / "default.json"
        if default_file.exists():
            return self._load_json(default_file)
        
        # 4. 返回空数据
        logger.warning(
            f"No mock data found for service={service_name}, scenario={scenario}"
        )
        return {"error": "Mock data not found"}
    
    def _load_json(self, file_path: Path) -> dict[str, Any]:
        """加载 JSON 文件"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(f"Loaded mock data from {file_path.name}")
            return data
        except Exception as e:
            logger.error(f"Failed to load {file_path}: {e}")
            return {"error": str(e)}
    
    def list_scenarios(self, service_name: str) -> list[str]:
        """列出服务的所有可用场景"""
        service_dir = self.mock_data_dir / service_name
        if not service_dir.exists():
            return []
        
        scenarios = []
        for json_file in service_dir.glob("*.json"):
            scenarios.append(json_file.stem)
        return scenarios


# 全局单例
_mock_loader: MockDataLoader | None = None


def get_mock_loader() -> MockDataLoader:
    """获取全局 Mock 数据加载器"""
    global _mock_loader
    if _mock_loader is None:
        _mock_loader = MockDataLoader()
    return _mock_loader
