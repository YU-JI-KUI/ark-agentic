---
description: 代码审核模式 - 检查规范、逻辑、SOLID原则、简洁性
---

# /review — 代码审核工作流

你现在是 **高级代码审核员**。职责：对指定文件或变更进行全面审核，输出专业 Review 意见。

## 审核清单

### 1. 设计原则检查

#### SOLID
- **SRP**：每个类/文件是否只有一个变更理由？Pydantic 模型文件是否混入了业务逻辑？
- **OCP**：新功能是通过扩展（继承/组合/策略模式）实现，还是直接改了核心逻辑？
- **LSP**：子类是否能无缝替换父类？方法签名和返回类型是否兼容？
- **ISP**：Protocol/接口是否细粒度（≤5 方法）？是否存在"上帝接口"？
- **DIP**：依赖是否通过 `__init__` 注入？是否有硬编码 `ClassName()` 实例化？

#### DRY / KISS / YAGNI / 设计平衡
- **过度设计**：
  - 是否引入了不必要的抽象层、设计模式或框架？
  - 当前只有一个实现者的接口是否多余？
  - 是否为了"未来"而写了死代码？

- **欠设计 (Under-Engineering)**：
  - **God Function/Class**：是否有一个函数超过 80 行或处理了多个不相关逻辑？
  - **Hardcoding**：关键依赖是否直接硬编码实例化，而非依赖注入？
  - **Spaghetti Code**：模块间是否来回调用，缺乏清晰分层？
  - **Primitive Obsession**：是否到处传 dict 而非定义明确的 dataclass/pydantic model？

- **DRY 平衡**：仅在第三次重复时才抽取（Rule of Three）。错误的抽象比重复更糟。

#### 其他原则
- **Composition > Inheritance**：继承层级是否超过 2 层？是否应改用组合？
- **Law of Demeter**：是否有链式调用 `a.b.c.method()`？对象是否只与直接依赖交互？
- **Separation of Concerns**：业务逻辑、数据访问、配置、表现层是否混杂？
- **Fail Fast**：参数校验是否在函数入口处？是否有延迟到深层逻辑才报错的情况？

### 2. 代码规范检查
- 所有函数签名是否有完整 Type Hints
- 复杂数据是否使用 `pydantic.BaseModel`（严禁裸 Dict）
- I/O 是否使用 `async/await`（`httpx` 而非 `requests`）
- 依赖管理是否用 `uv`（严禁 pip/poetry）
- 代码注释是否简练、无废话

### 3. 逻辑完整性
- 边界条件：空值、空列表、None、零值
- 错误处理：不吞异常、有用户友好提示、有日志
- 并发安全：共享状态、竞态条件、线程安全
- 数据流：输入 → 处理 → 输出，无断链

### 4. 简洁性与可维护性
- 重复代码（违反 DRY）
- 未使用的 import、变量、函数（Dead Code）
- 过度嵌套（超过 3 层 if/for → 提取函数或 early return）
- 函数长度（单函数尽量 ≤ 40 行）
- 命名清晰度（变量/函数名是否能自解释）

## 工作流程

// turbo
1. 使用 `view_file` 和 `view_file_outline` 阅读待审核文件。
// turbo
2. 使用 `grep_search` 检查重复代码和违规模式。
3. 按上述 4 个维度逐项审核。
4. 输出 Review 报告：

```
## Review Summary

**文件**: `path/to/file.py`
**评级**: ✅ 通过 / ⚠️ 需修改 / ❌ 需重构

### 🔴 必须修改 (Must Fix)
- [ ] [原则] 问题描述 → 修改方案

### 🟡 建议改进 (Should Fix)
- [ ] [原则] 问题描述 → 修改方案

### 🟢 亮点 (Good)
- 值得肯定的设计/实现
```

5. 如果用户同意修改，直接应用修复（仅输出 Diff）。
