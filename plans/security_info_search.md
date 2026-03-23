在Agent项目中需要处理用户股票信息查询相关问题。
由于ASR识别不准或用户记忆不全导致股票信息无法获得。

以下是**轻量级股票实体识别与纠错技术方案**。

---

### 一、 技术架构方案

该方案分为 **“离线索引构建”** 和 **“在线检索流水线”** 两个部分。

#### 1. 离线：构建多维内存索引
将股票基础信息（如 A 股约 5000+ 条数据）加载到内存中，构建以下映射表：
* **精确索引**：`{代码: 实体}`、`{全称: 实体}`、`{简称: 实体}`。
* **拼音索引**：`{全拼: 实体}`、`{首字母缩写: 实体}`（用于处理 ASR 同音字）。
* **别名索引**：`{俗称: 实体}`（如“茅台”对应“贵州茅台”）。

#### 2. 在线：处理流水线 (Pipeline)


1.  **实体提取 (Extraction)**：
    * 利用 LLM 从用户 Query 中提取疑似“股票相关片段”。
    * *Prompt 示例*：“请从用户话术中提取可能是股票名称、代码或拼音的片段。Query:‘帮我看看宁德实代和招行’ -> Output: `['宁德实代', '招行']`”。
2.  **多路匹配 (Multi-path Matching)**：
    * **路径 A (正则)**：识别 6 位数字代码。
    * **路径 B (拼音)**：将提取片段转为拼音，与“拼音索引”匹配（解决 ASR 错误的核心）。
    * **路径 C (模糊字符)**：使用 `Levenshtein` 距离计算文本相似度（解决用户记忆偏差）。
3.  **打分与排序 (Scoring)**：
    * 综合权重 = $\alpha \cdot \text{文本相似度} + \beta \cdot \text{拼音相似度}$。
4.  **决策逻辑 (Decision)**：
    * **Score > 0.9**：自动锁定，直接返回结果。
    * **0.6 < Score < 0.9**：待澄清，将 Top 2-3 候选词交给 LLM 发起反问。
    * **Score < 0.6**：放弃，告知未匹配。

---

### 二、 推荐依赖库

这套方案追求“轻量”，因此避开了复杂的深度学习框架（如 PyTorch/TensorFlow），仅需以下 Python 库：

| 库名称 | 用途 | 核心优势 |
| :--- | :--- | :--- |
| **`rapidfuzz`** | 模糊匹配 / 编辑距离 | C++ 实现，速度极快；比传统的 `fuzzywuzzy` 性能高出一个数量级。 |
| **`pypinyin`** | 中文转拼音 | 支持多种拼音风格（全拼、首字母、声调），是处理 ASR 同音错别字的神器。 |
| **`pandas`** | 字典管理 | 方便加载 CSV/Excel 格式的股票列表，进行快速的向量化预处理。 |
| **`ahocorasick`** (可选) | 多模式匹配 | 如果股票字典非常大，用于快速从长文本中扫描关键词（AC 自动机）。 |

---

### 三、 核心伪代码示例

```python
from rapidfuzz import process, fuzz
from pypinyin import pinyin, Style

# 1. 准备数据（实际从CSV读取）
stock_dict = {
    "600519": {"name": "贵州茅台", "pinyin": "guizhoumaotai", "abbr": "gzmt"},
    "300750": {"name": "宁德时代", "pinyin": "ningdeshidai", "abbr": "ndsd"}
}

def get_pinyin_str(text):
    return "".join([i[0] for i in pinyin(text, style=Style.NORMAL)])

def match_stock(query_segment):
    # a. 尝试代码匹配
    if query_segment.isdigit() and query_segment in stock_dict:
        return stock_dict[query_segment], 1.0
    
    # b. 拼音相似度匹配 (针对 ASR 纠错)
    target_pinyin = get_pinyin_str(query_segment)
    all_pinyins = [v['pinyin'] for v in stock_dict.values()]
    # 提取拼音最接近的 Top1
    best_pinyin = process.extractOne(target_pinyin, all_pinyins, scorer=fuzz.Ratio)
    
    # c. 文本相似度匹配 (针对 记忆偏差)
    all_names = [v['name'] for v in stock_dict.values()]
    best_name = process.extractOne(query_segment, all_names, scorer=fuzz.WRatio)
    
    # 取二者最高分进行决策...
    return best_pinyin, best_name
```

---

### 四、 经验总结与避坑

* **处理“重名”**：金融市场有很多简称相似的股票（如“建设银行”与“建设机械”），在模糊匹配后，**一定要保留 Top N**，让 Agent 有机会在上下文中确认。
* **动态更新**：股票代码和简称会有变动（如 ST 脱帽、更名），建议将股票字典挂载在 Redis 或简单的定时内存任务中。
* **ASR 降噪**：如果 ASR 识别出“我想看下**那个**宁德时代”，LLM 提取时容易带上“那个”。建议在模糊匹配前去掉常见的金融停用词（如“股票”、“代码”、“价格”）。

**需要我为您写一个更完整的 Python 类来实现这个逻辑，还是您想先试试这些库的集成？**