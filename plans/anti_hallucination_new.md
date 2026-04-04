# 单轮闭环 Cite 幻觉检测方案设计

## 一、核心目标

本方案旨在以**最小工程复杂度**解决大模型回答中的**幻觉问题（Hallucination）**，重点关注：

* 对答案的**置信度打分**
* 对关键事实（实体 / 时间 / 数字）的**可验证性校验**
* 不引入额外模型或多轮推理，保持**低延迟（ms级）**

### 核心原则

1. **模型负责生成证据（cite）**
2. **系统负责验证证据（deterministic）**
3. **评分必须由工具输出，不由模型决定**

---

## 二、整体架构

采用**单轮闭环（Single-pass loop）**设计：

```text
LLM生成（answer + citations）
        ↓
ValidateTool（确定性校验）
        ↓
输出最终结果（answer + score + errors）
```

### 特点

* 无需二次推理（避免延迟增加）
* 无需复杂NER模型
* 可直接嵌入Agent体系

---

## 三、Cite结构设计

采用**结构化引用（Structured Citation）**，避免自然语言不确定性。

### 输出格式

```json
{
  "answer": "2024年苹果公司营收达到3,000亿美元，同比增长5%",
  "citations": [
    {
      "value": "苹果公司",
      "type": "ENTITY",
      "source": "tool_1"
    },
    {
      "value": "2024年",
      "type": "TIME",
      "source": "context"
    },
    {
      "value": "3,000亿美元",
      "type": "NUMBER",
      "source": "tool_1"
    },
    {
      "value": "5%",
      "type": "NUMBER",
      "source": "tool_1"
    }
  ]
}
```

### 字段说明

| 字段     | 含义                     |
| ------ | ---------------------- |
| value  | 实际文本值                  |
| type   | ENTITY / TIME / NUMBER |
| source | tool_x / context       |

### 约束

* 必须覆盖所有关键事实
* 不允许自由文本cite（如 `[cite:xxx]`）
* source必须明确（tool / context）

---

## 四、Validate 工具设计

## 4.1 目标

对模型输出进行**确定性校验**：

* cite 是否真实存在
* 是否存在未标注关键元素
* 工具数据是否被篡改

---

## 4.2 输入

```json
{
  "answer": "...",
  "citations": [...],
  "tool_output": "...",
  "context": "..."
}
```

---

## 4.3 输出

```json
{
  "score": 0.7,
  "errors": [
    {
      "type": "CITE_NOT_FOUND",
      "value": "100亿",
      "source": "tool"
    },
    {
      "type": "UNCITED",
      "value": "2024年"
    }
  ]
}
```

---

## 4.4 校验逻辑

### Step1：校验 cite 是否真实存在

```python
def check_citation(citation, tool_text, ctx_text):
    v = citation["value"]
    src = citation["source"]

    if src.startswith("tool"):
        return v in tool_text
    elif src == "context":
        return v in ctx_text
    return False
```

---

### Step2：自动抽取关键元素（兜底）

使用**轻量规则 + Trie**（无需复杂NER）

#### 正则抽取

```python
import re

TIME_PATTERN = r'\d{4}年|\d{4}-\d{2}-\d{2}'
NUMBER_PATTERN = r'\d+(\.\d+)?(亿|万|%)?'

def extract_elements(text):
    times = re.findall(TIME_PATTERN, text)
    numbers = re.findall(NUMBER_PATTERN, text)
    return times, numbers
```

---

### Step3：Trie实体识别（工程优化）

用于识别金融实体（公司 / 股票）

```python
class Trie:
    def __init__(self):
        self.root = {}

    def insert(self, word):
        node = self.root
        for c in word:
            node = node.setdefault(c, {})
        node["#"] = True

    def search(self, text):
        results = []
        for i in range(len(text)):
            node = self.root
            j = i
            while j < len(text) and text[j] in node:
                node = node[text[j]]
                if "#" in node:
                    results.append(text[i:j+1])
                j += 1
        return results
```

---

### Step4：未标注元素检测

```python
def find_uncited(answer, citations):
    times, numbers = extract_elements(answer)
    cited = {c["value"] for c in citations}

    uncited = []

    for v in times + numbers:
        if v not in cited:
            uncited.append(v)

    return uncited
```

---

### Step5：评分机制

```python
def compute_score(errors):
    base = 1.0
    penalty = 0.2 * len(errors)
    return max(0, base - penalty)
```

---

## 五、执行生命周期

完整执行流程如下：

---

### Step 1：用户请求

```text
用户问题 → Agent
```

---

### Step 2：工具调用

```text
Agent → Tool
       → 返回 tool_output
```

---

### Step 3：LLM生成（带cite）

```text
输入：
  - 用户问题
  - tool_output
  - context

输出：
  answer + citations
```

---

### Step 4：ValidateTool 校验

```text
输入：
  answer + citations + tool_output + context

处理：
  - 校验cite真实性
  - 抽取未标注元素
  - 计算score

输出：
  score + errors
```

---

### Step 5：最终输出

```json
{
  "answer": "...",
  "score": 0.7,
  "errors": [...]
}
```

---

## 六、方案特点总结

### 优点

* ✅ 无需额外模型（低成本）
* ✅ 毫秒级执行（Trie + regex）
* ✅ 强可解释性（cite + errors）
* ✅ 易接入Agent体系

---

### 限制

* ❗ 依赖字符串匹配（非语义级）
* ❗ 对复杂推理场景覆盖有限
* ❗ cite质量依赖prompt约束

---

## 七、适用场景

* 金融问答（强结构化数据）
* 工具增强型Agent
* 实时系统（低延迟要求）

---

## 八、一句话总结

> 通过“模型生成证据 + 工具验证证据”，用最小成本实现可解释的幻觉控制闭环

---
