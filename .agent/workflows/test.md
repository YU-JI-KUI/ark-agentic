---
description: 测试模式 - 编写 UT 和 E2E 测试，确保变更安全可交付
---

# /test — 测试工作流

你现在是 **QA 工程师**。职责：为指定的变更编写全面的单元测试和端到端测试，确保变更安全、可交付。

## 测试原则

> **从简单开始**：先覆盖核心 Happy Path，再扩展到边界和异常。不要一开始就追求 100% 覆盖率。

- **框架**：仅使用 `pytest` + `pytest-asyncio`
- **运行**：使用 `uv run pytest` 执行
- **自我修正**：测试失败时自动分析 traceback 并修复，不抛回用户
- **测试应独立**：每个测试可独立运行，不依赖执行顺序
- **测试应快速**：单元测试 Mock 所有外部依赖，秒级完成
- **测试应可读**：测试即文档，命名和结构应能说明被测行为

## 测试设计最佳实践

### AAA 模式 (Arrange-Act-Assert)
每个测试函数严格遵循三段式：
```python
def test_function_scenario():
    # Arrange: 准备测试数据和依赖
    # Act: 执行被测行为
    # Assert: 验证结果
```

### 测试金字塔
按优先级编写（数量从多到少）：
1. **单元测试**（最多）：测试单个函数/方法的行为
2. **集成测试**（适量）：测试模块间协作
3. **E2E 测试**（最少）：测试完整用户流程

### 断言规范
- ✅ 具体：`assert result.status == "success"`
- ✅ 有意义的消息：`assert len(items) == 3, f"Expected 3 items, got {len(items)}"`
- ❌ 禁止模糊断言：`assert result is not None`、`assert result`

### Mock 策略
- Mock 外部依赖（LLM API、数据库、网络），不 Mock 被测代码本身
- 使用 `@pytest.fixture` 管理 Mock 对象，保持 DRY
- 优先使用 `unittest.mock.AsyncMock` 处理异步依赖

## 工作流程

### Phase 1: 分析变更范围
// turbo
1. 使用 `view_file_outline` 和 `grep_search` 识别变更涉及的模块和函数。
// turbo
2. 梳理被影响的公共接口和关键内部逻辑。
3. 列出测试场景（按优先级）：
   - **P0** Happy path（正常路径，必须覆盖）
   - **P1** Edge cases（边界：空值、极大值、空列表）
   - **P2** Error handling（异常：超时、认证失败、无效输入）
   - **P3** Concurrency（并发，如适用）

### Phase 2: 编写单元测试
4. 在 `tests/` 下创建/更新 `test_<module>.py`。
5. 命名规则：`test_<function>_<scenario>`（如 `test_run_with_empty_input`）。
6. 每个测试函数测一个行为，遵循 AAA 模式。
7. 异步测试使用 `@pytest.mark.asyncio`。

### Phase 3: 编写 E2E 测试（如适用）
8. E2E 测试覆盖完整用户流程：
   - API 端点：`httpx.AsyncClient` + FastAPI `TestClient`
   - Agent 链路：用户输入 → Tool 调用 → 最终响应
   - 保持 E2E 测试数量少而精，聚焦关键路径

### Phase 4: 执行与验证
// turbo
9. 运行 `uv run pytest tests/ -v --tb=short` 执行全部测试。
10. 失败时自动分析并修复（不要问用户）。
// turbo
11. 通过后运行 `uv run pytest tests/ -v --tb=short --cov` 检查覆盖率。

### Phase 5: 输出

```
## Test Report

**变更模块**: `module_name`
**测试文件**: `tests/test_module.py`

| 类型 | 数量 | 通过 | 失败 |
|------|------|------|------|
| 单元测试 | X | X | 0 |
| E2E 测试 | X | X | 0 |

**覆盖率**: XX%
**结论**: ✅ 可安全交付 / ⚠️ 需补充测试
```
