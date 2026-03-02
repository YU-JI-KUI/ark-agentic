# Agent 前端页面拆分 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 insurance / securities 从单页混合前端拆分为独立页面，并通过 `/insurance`、`/securities` 路由访问，切换 Agent 时整页跳转。

**Architecture:** 保持后端 `/chat` 协议不变，仅新增页面路由与静态页面拆分。`insurance.html` 和 `securities.html` 分别承载各自 UI 与卡片渲染逻辑；跨页面仅保留最小公共逻辑（会话存储键与基础发送流程），避免业务渲染互相干扰。

**Tech Stack:** FastAPI、原生 HTML/CSS/JavaScript、pytest

---

### Task 1: 为新路由写失败测试（先测后改）

**Files:**
- Modify: `tests/test_app_integration.py`
- Test: `tests/test_app_integration.py`

**Step 1: Write the failing test**

在 `tests/test_app_integration.py` 增加 3 个测试：

```python
def test_insurance_page_route(client: TestClient):
    resp = client.get("/insurance")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_securities_page_route(client: TestClient):
    resp = client.get("/securities")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_root_route_keeps_html_entry(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_integration.py -k "insurance_page_route or securities_page_route" -v`
Expected: FAIL（提示 404，因为新路由尚未实现）

**Step 3: Write minimal implementation**

暂不实现业务逻辑；只确认测试确实失败，进入 Task 2 完成实现。

**Step 4: Re-run to keep failure signal explicit**

Run: `pytest tests/test_app_integration.py -k "insurance_page_route or securities_page_route" -v`
Expected: 仍 FAIL（确保失败由缺路由引起）

**Step 5: Commit**

```bash
git add tests/test_app_integration.py
git commit -m "test: add failing route tests for insurance and securities pages"
```

---

### Task 2: 实现 `/insurance` 与 `/securities` 页面路由

**Files:**
- Modify: `src/ark_agentic/app.py`
- Test: `tests/test_app_integration.py`

**Step 1: Write the failing test**

复用 Task 1 已添加测试，不新增。

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_integration.py -k "insurance_page_route or securities_page_route" -v`
Expected: FAIL

**Step 3: Write minimal implementation**

在 `src/ark_agentic/app.py` 的 `root()` 附近新增：

```python
@app.get("/insurance", include_in_schema=False)
async def insurance_page():
    page = _STATIC_DIR / "insurance.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    raise HTTPException(status_code=404, detail="insurance page not found")


@app.get("/securities", include_in_schema=False)
async def securities_page():
    page = _STATIC_DIR / "securities.html"
    if page.is_file():
        return FileResponse(str(page), media_type="text/html")
    raise HTTPException(status_code=404, detail="securities page not found")
```

> 注意：不要改 `/chat` 协议与现有 agent 注册逻辑。

**Step 4: Run test to verify it passes (or moves to next blocker)**

Run: `pytest tests/test_app_integration.py -k "insurance_page_route or securities_page_route" -v`
Expected: 如果页面文件未创建，会 404；这是预期的下一步 blocker（Task 3/4 解决）。

**Step 5: Commit**

```bash
git add src/ark_agentic/app.py tests/test_app_integration.py
git commit -m "feat: add dedicated routes for insurance and securities pages"
```

---

### Task 3: 创建 `insurance.html` 并移除证券逻辑

**Files:**
- Create: `src/ark_agentic/static/insurance.html`
- Modify: `src/ark_agentic/static/index.html`
- Create: `tests/test_static_insurance_page_contract.py`
- Test: `tests/test_static_insurance_page_contract.py`

**Step 1: Write the failing test**

新增 `tests/test_static_insurance_page_contract.py`：

```python
from pathlib import Path

INSURANCE_HTML = Path(__file__).resolve().parents[1] / "src" / "ark_agentic" / "static" / "insurance.html"


def test_insurance_page_exists_and_targets_insurance_agent():
    content = INSURANCE_HTML.read_text(encoding="utf-8")
    assert "agent_id: selectedAgent" not in content
    assert 'agent_id: "insurance"' in content or "agent_id:'insurance'" in content


def test_insurance_page_does_not_render_securities_templates():
    content = INSURANCE_HTML.read_text(encoding="utf-8")
    assert "renderAccountOverviewCard" not in content
    assert "holdings_list_card" not in content
    assert "accountTypeSelect" not in content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_static_insurance_page_contract.py -v`
Expected: FAIL（文件不存在）

**Step 3: Write minimal implementation**

- 从现有 `index.html` 复制生成 `insurance.html`
- 在 `insurance.html` 中完成最小改造：
  - `agent_id` 固定为 `insurance`
  - 删除证券账户类型 selector 与其事件逻辑
  - 删除证券模板卡渲染函数与 template 分支
  - Agent 下拉切换改为：选中 securities 时 `window.location.href = "/securities"`

- 将 `index.html` 简化为入口页（可保留当前结构），至少保证可导航到 `/insurance`。

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_static_insurance_page_contract.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ark_agentic/static/insurance.html src/ark_agentic/static/index.html tests/test_static_insurance_page_contract.py
git commit -m "feat: split insurance page and remove securities rendering logic"
```

---

### Task 4: 创建 `securities.html` 并保留证券模板卡渲染

**Files:**
- Create: `src/ark_agentic/static/securities.html`
- Create: `tests/test_static_securities_page_contract.py`
- Modify: `tests/test_static_index_render_contract.py`
- Test: `tests/test_static_securities_page_contract.py`

**Step 1: Write the failing test**

新增 `tests/test_static_securities_page_contract.py`：

```python
from pathlib import Path

SECURITIES_HTML = Path(__file__).resolve().parents[1] / "src" / "ark_agentic" / "static" / "securities.html"


def test_securities_page_exists_and_targets_securities_agent():
    content = SECURITIES_HTML.read_text(encoding="utf-8")
    assert 'agent_id: "securities"' in content or "agent_id:'securities'" in content
    assert "accountTypeSelect" in content


def test_securities_page_contains_template_renderers():
    content = SECURITIES_HTML.read_text(encoding="utf-8")
    assert "function renderAccountOverviewCard(data)" in content
    assert "function renderHoldingsListCard(template)" in content
    assert "function renderTemplateCard(template, containerEl)" in content
```

并把原 `tests/test_static_index_render_contract.py` 调整为针对 `securities.html` 读取（避免继续绑定 `index.html`）。

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_static_securities_page_contract.py tests/test_static_index_render_contract.py -v`
Expected: FAIL（`securities.html` 尚不存在或契约不满足）

**Step 3: Write minimal implementation**

- 从现有 `index.html` 拷贝生成 `securities.html`
- 保留证券所需逻辑：
  - 固定 `agent_id = "securities"`
  - 保留账户类型 selector
  - 保留 template 卡渲染函数（overview/holdings/cash/security_detail）
  - Agent 下拉切换改为：选中 insurance 时 `window.location.href = "/insurance"`
- 去掉保险页专属快捷入口文案（如保险保单场景），改为证券场景快捷项（最小可用即可）

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_static_securities_page_contract.py tests/test_static_index_render_contract.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ark_agentic/static/securities.html tests/test_static_securities_page_contract.py tests/test_static_index_render_contract.py
git commit -m "feat: add securities page with dedicated template-card rendering"
```

---

### Task 5: 端到端回归与脚手架模板同步

**Files:**
- Modify: `src/ark_agentic/cli/main.py`
- Modify: `src/ark_agentic/cli/templates.py`
- Test: `tests/test_app_integration.py`
- Test: `tests/test_static_insurance_page_contract.py`
- Test: `tests/test_static_securities_page_contract.py`

**Step 1: Write the failing test**

为脚手架同步增加最小断言（可放入现有 CLI 相关测试文件；若当前无现成测试，先写 TODO 断言并在本任务实现）。

示例断言方向：`ark-agentic init --api` 生成静态目录时不只复制 `index.html`，还能包含 `insurance.html` 与 `securities.html`。

**Step 2: Run test to verify it fails**

Run: `pytest tests -k "cli or app_integration or static" -v`
Expected: FAIL（模板复制逻辑尚未更新）

**Step 3: Write minimal implementation**

- 更新 `src/ark_agentic/cli/main.py`：复制静态页面时从“仅 index.html”扩展为复制 `{index.html, insurance.html, securities.html}`（文件存在才复制）
- 更新 `src/ark_agentic/cli/templates.py`（如 API 模板内有静态入口/注释与路由示例），保持与主工程一致：支持 `/insurance`、`/securities`

**Step 4: Run full verification**

Run: `pytest tests/test_app_integration.py tests/test_static_index_render_contract.py tests/test_static_insurance_page_contract.py tests/test_static_securities_page_contract.py -v`
Expected: 全部 PASS

再跑一次核心回归：

Run: `pytest tests/test_sse_template.py -v`
Expected: PASS（确认证券模板事件链路未被页面拆分破坏）

**Step 5: Commit**

```bash
git add src/ark_agentic/cli/main.py src/ark_agentic/cli/templates.py tests/test_app_integration.py tests/test_static_index_render_contract.py tests/test_static_insurance_page_contract.py tests/test_static_securities_page_contract.py
git commit -m "chore: align scaffold templates with split insurance and securities pages"
```

---

## 验收清单（执行完成后逐项确认）

- [ ] `/insurance`、`/securities` 返回 200 且可访问
- [ ] insurance 页不包含证券卡片渲染逻辑
- [ ] securities 页保留证券模板卡渲染逻辑
- [ ] Agent 下拉切换触发整页跳转（非单页条件分支）
- [ ] `/chat` 接口与 SSE 行为保持兼容
- [ ] 脚手架 `init --api` 生成项目与主工程静态结构一致
