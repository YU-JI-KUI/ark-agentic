import React from 'react';

// === 核心交互组件：允许直接在页面上点击编辑文字 ===
const EditableText = ({ text, className = "" }) => {
  const save = (el) => {
    // 允许换行，提取内部文本
    const newText = el.innerText.trim();
    if (newText && newText !== text) {
      fetch('/api/save', {
        method: 'POST',
        body: JSON.stringify({ oldText: text, newText }),
      }).catch(err => console.error('Save failed:', err));
    }
  };

  const handleKeyDown = (e) => {
    // Shift+Enter 允许换行，纯 Enter 触发保存并失焦
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.blur();
    }
  };

  // 如果 text 里有换行，渲染时用 <br/> 替代，保证页面显示正确
  return (
    <span
      contentEditable
      suppressContentEditableWarning
      onBlur={(e) => save(e.currentTarget)}
      onKeyDown={handleKeyDown}
      className={`outline-none focus:bg-slate-200/50 focus:ring-1 focus:ring-slate-300 px-1 rounded transition-colors cursor-text whitespace-pre-wrap ${className}`}
      dangerouslySetInnerHTML={{ __html: text.replace(/\n/g, '<br/>') }}
    />
  );
};

// === 基础色块组件 ===
const BaseBlock = ({ title, bgClass = "bg-white", textClass = "text-slate-700", borderClass = "border border-slate-200", className = "", children }) => (
  <div className={`flex flex-col items-center justify-center p-1.5 text-center text-xs shadow-sm rounded-md transition-all duration-200 hover:shadow-md hover:border-[#EA5504] hover:-translate-y-0.5 ${bgClass} ${textClass} ${borderClass} ${className}`}>
    <EditableText text={title} className="w-full block font-medium" />
    {children}
  </div>
);

// === 组合/容器色块组件 ===
const GroupBlock = ({ title, bgClass = "bg-slate-50/50", borderClass = "border border-slate-200", headerClass = "text-slate-700 font-semibold bg-slate-100/50 border-b border-slate-200", contentClass = "gap-1.5 p-1.5", className = "", children }) => (
  <div className={`flex flex-col shadow-sm rounded-md overflow-hidden ${bgClass} ${borderClass} ${className}`}>
    {title && (
      <div className={`text-center text-xs p-1.5 ${headerClass}`}>
        <EditableText text={title} />
      </div>
    )}
    <div className={`flex-1 flex flex-wrap content-start ${contentClass}`}>
      {children}
    </div>
  </div>
);

// === 左侧层级行组件 ===
const LayerRow = ({ label, labelBg = "bg-gradient-to-b from-[#EA5504] to-[#d14b03]", compact = false, children }) => (
  <div className={`flex flex-row mb-2.5 shadow-sm bg-white rounded-lg overflow-hidden border border-slate-200 transition-all hover:border-slate-300 ${compact ? 'items-stretch' : ''}`}>
    <div className={`w-16 md:w-20 shrink-0 flex items-center justify-center text-white font-bold text-center tracking-wide ${labelBg} ${compact ? 'py-0.5 px-1 text-xs leading-tight' : 'p-2 text-xs md:text-sm'}`}>
      <EditableText text={label} />
    </div>
    <div className={`flex-1 flex flex-col bg-slate-50/30 ${compact ? 'gap-1 py-1 px-2' : 'gap-2 p-2'}`}>
      {children}
    </div>
  </div>
);

// === 右侧橙色注释卡片组件 ===
const NoteCard = ({ text, bgClass = "bg-white", textClass = "text-slate-600", borderClass = "border-l-4 border-[#EA5504] border-y border-r border-slate-200" }) => {
  // NoteCard 允许多行
  const save = (el) => {
    const newText = el.innerText.trim();
    if (newText && newText !== text) {
      fetch('/api/save', {
        method: 'POST',
        body: JSON.stringify({ oldText: text, newText }),
      }).catch(err => console.error('Save failed:', err));
    }
  };

  return (
    <div className={`${bgClass} ${textClass} ${borderClass} p-3 text-xs mb-3 shadow-sm rounded-r-md text-left leading-relaxed font-medium transition-all hover:shadow-md`}>
      <div
        contentEditable
        suppressContentEditableWarning
        onBlur={(e) => save(e.currentTarget)}
        className="outline-none focus:bg-slate-50 rounded px-1 cursor-text whitespace-pre-wrap"
        dangerouslySetInnerHTML={{ __html: text.replace(/\n/g, '<br/>') }}
      />
    </div>
  );
};

export default function ArchitectureDiagram() {
  // 定义高亮样式（平安橙主题）
  const highlightGroupBg = "bg-[#FFF5F0]/80";
  const highlightGroupBorder = "border border-[#EA5504]/30";
  const highlightGroupHeader = "text-[#EA5504] font-bold bg-[#FFF5F0] border-b border-[#EA5504]/20";
  
  const highlightBlockBg = "bg-[#FFF5F0]";
  const highlightBlockBorder = "border border-[#EA5504]/40";
  const highlightBlockText = "text-[#EA5504]";

  return (
    <div className="min-h-screen bg-slate-50 p-6 font-sans text-slate-800 select-none">
      
      <div className="max-w-6xl mx-auto bg-white p-6 shadow-xl ring-1 ring-slate-900/5 rounded-xl">
        
        {/* 顶部标题区 */}
        <div className="mb-6 flex items-center border-b-2 border-slate-100 pb-4">
          <h1 className="text-3xl font-bold flex items-center tracking-tight">
            <EditableText text="Agentic 技术架构" className="text-slate-800" />
          </h1>
        </div>

        <div className="flex flex-col lg:flex-row gap-4">
          
          {/* ================= 左侧：核心架构主视图 ================= */}
          <div className="flex-1 flex flex-col">
            
            {/* 0. 业务
能力层（新增） */}
            <LayerRow label="业务
能力" labelBg="bg-gradient-to-b from-[#EA5504] to-[#d14b03]" compact>
              <div className="flex flex-row gap-1.5 w-full items-stretch py-0.5">
                <BaseBlock title="千人千面 · 个性化" className="flex-1 text-[11px] py-1.5" bgClass="bg-amber-50" borderClass="border border-amber-300" textClass="text-amber-700 font-medium" />
                <BaseBlock title="全程陪伴 · 跨会话" className="flex-1 text-[11px] py-1.5" bgClass="bg-amber-50" borderClass="border border-amber-300" textClass="text-amber-700 font-medium" />
                <BaseBlock title="主动服务触达" className="flex-1 text-[11px] py-1.5" bgClass="bg-sky-50" borderClass="border border-sky-200" textClass="text-sky-800 font-medium" />
                <BaseBlock title="✦ 自主任务执行" className="flex-1 text-[11px] py-1.5" bgClass="bg-slate-50" borderClass="border border-dashed border-slate-300" textClass="text-slate-400 font-medium" />
                <BaseBlock title="✦ 主动进化 · 自我增强" className="flex-1 text-[11px] py-1.5" bgClass="bg-slate-50" borderClass="border border-dashed border-slate-300" textClass="text-slate-400 font-medium" />
              </div>
            </LayerRow>

            {/* 1. 前端层（薄层） */}
            <LayerRow label="前端" compact>
              <div className="flex flex-row gap-1.5 w-full items-stretch py-0.5">
                <BaseBlock title="MiniSA (Demo)" className="flex-1 text-[11px] py-1.5" />
                <BaseBlock title="Agent Studio" className="flex-1 text-[11px] py-1.5" />
                <BaseBlock title="SA前端" className="flex-1 text-[11px] py-1.5" />
                <BaseBlock title="寿险微前端" className="flex-1 text-[11px] py-1.5" />
              </div>
            </LayerRow>

            {/* 2. 接入层 */}
            <LayerRow label="接入层" compact>
              <div className="flex flex-row gap-1.5 w-full py-0.5">
                <BaseBlock title="流式 · SSE (AGUI & ALONE)" className="flex-1 text-[11px] py-1.5" />
                <BaseBlock title="非流式 · Restful API" className="flex-1 text-[11px] py-1.5" />
              </div>
            </LayerRow>

            {/* 3. Agentic 层（主体 + 右侧元智能体纵栏） */}
            <LayerRow label="Agentic">
              <div className="flex flex-row gap-2 w-full">

                {/* 左侧主体：四部分自上而下 */}
                <div className="flex-1 flex flex-col gap-2 min-w-0">

                  {/* ① 输出与呈现 */}
                  <GroupBlock title="输出与呈现" bgClass={highlightGroupBg} borderClass={highlightGroupBorder} headerClass={highlightGroupHeader} contentClass="grid grid-cols-2 gap-2 p-2">
                    {/* 思考态 */}
                    <div className="rounded-md border border-slate-200 bg-white overflow-hidden flex flex-col">
                      <div className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-1 border-b border-slate-200 text-center"><EditableText text="思考态" /></div>
                      <div className="flex flex-col gap-1 p-1.5 bg-slate-50">
                        <BaseBlock title="思维链路 · CoT 流式输出 | 步骤分解" className="text-[10px] py-0.5" />
                        <BaseBlock title="过程追踪 · 工具调用 | 并行任务" className="text-[10px] py-0.5" />
                      </div>
                    </div>
                    {/* 生成态 */}
                    <div className="rounded-md border border-slate-200 bg-white overflow-hidden flex flex-col">
                      <div className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-1 border-b border-slate-200 text-center"><EditableText text="生成态" /></div>
                      <div className="flex flex-col gap-1 p-1.5 bg-slate-50">
                        <BaseBlock title="A2UI · Template | Component | Dynamic" className="text-[10px] py-0.5" />
                        <BaseBlock title="样式 · Markdown | 表格 | 卡片 | 列表" className="text-[10px] py-0.5" />
                      </div>
                    </div>
                  </GroupBlock>

                  {/* ② 执行与编排 */}
                  <GroupBlock title="执行与编排" bgClass={highlightGroupBg} borderClass={highlightGroupBorder} headerClass={highlightGroupHeader} contentClass="grid grid-cols-2 gap-2 p-2">
                    {/* Agent Runtime */}
                    <div className="rounded-md border border-slate-200 bg-white overflow-hidden flex flex-col">
                      <div className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-1 border-b border-slate-200 text-center"><EditableText text="Agent Runtime" /></div>
                      <div className="flex flex-col gap-1 p-1.5 bg-slate-50">
                        <BaseBlock title="Agent Loop  · 思考，规划 -工具调用" className="text-[10px] py-0.5" />
                        <BaseBlock title="Spawn(子任务) · 复杂任务并行调度" className="text-[10px] py-0.5" />
                        <BaseBlock title="自我反思 · 输出评估与自动修正" className="text-[10px] py-0.5" />
                      </div>
                    </div>
                    {/* Skill Management */}
                    <div className="rounded-md border border-slate-200 bg-white overflow-hidden flex flex-col">
                      <div className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-1 border-b border-slate-200 text-center"><EditableText text="Skill Management" /></div>
                      <div className="flex flex-col gap-1 p-1.5 bg-slate-50">
                        <BaseBlock title="加载模式 · Full | Dynamic | Semantic" className="text-[10px] py-0.5" />
                        <BaseBlock title="生命周期  · 注册，匹配，过滤" className="text-[10px] py-0.5" />
                        <BaseBlock title="✦ 主动学习 · 对话沉淀为新 Skill" className="text-[10px] py-0.5" bgClass="bg-slate-100/80" borderClass="border border-dashed border-slate-400" textClass="text-slate-400" />
                      </div>
                    </div>
                  </GroupBlock>

                  {/* ③ 状态与记忆 */}
                  <GroupBlock title="状态与记忆" bgClass={highlightGroupBg} borderClass={highlightGroupBorder} headerClass={highlightGroupHeader} contentClass="flex flex-col gap-2 p-2">
                    <BaseBlock title="Context Engineering" className="w-full text-[10px]" />
                    <div className="grid grid-cols-3 gap-2 items-stretch">
                      {/* Session — 白底 + 浅灰边框，内部 slate-50 底色区分层次 */}
                      <div className="rounded-md border border-slate-200 bg-white overflow-hidden flex flex-col">
                        <div className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-1 border-b border-slate-200 text-center"><EditableText text="Session · 短期记忆" /></div>
                        <div className="flex flex-col gap-1 p-1.5 bg-slate-50">
                          <BaseBlock title="上下文压缩 · Compaction" className="text-[10px] py-0.5" />
                          <BaseBlock title="对话回放 · Replay" className="text-[10px] py-0.5" />
                        </div>
                      </div>
                      {/* Memory — 同样白底灰边，实现层用两列 */}
                      <div className="rounded-md border border-slate-200 bg-white overflow-hidden flex flex-col">
                        <div className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-1 border-b border-slate-200 text-center"><EditableText text="Memory · 长期记忆" /></div>
                        <div className="flex flex-col gap-1 p-1.5 bg-slate-50">
                          <div className="grid grid-cols-2 gap-1">
                            <BaseBlock title="MD文件IO" className="text-[10px] py-0.5" />
                            <BaseBlock title="Mem0" className="text-[10px] py-0.5" />
                          </div>
                          <BaseBlock title="知识沉淀 · 记忆更新 · 记忆检索" className="text-[10px] py-0.5 w-full" />
                        </div>
                      </div>
                      {/* Agent State — 同样白底灰边 */}
                      <div className="rounded-md border border-slate-200 bg-white overflow-hidden flex flex-col">
                        <div className="text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-1 border-b border-slate-200 text-center"><EditableText text="Agent State · 状态快照" /></div>
                        <div className="flex flex-col gap-1 p-1.5 bg-slate-50">
                          <BaseBlock title="Shared Context · 工具间数据共享" className="text-[10px] py-0.5" />
                          <BaseBlock title="Scratch Pad · 临时数据擦写" className="text-[10px] py-0.5" />
                        </div>
                      </div>
                    </div>
                  </GroupBlock>

                  {/* ④ 模型与工具 */}
                  <GroupBlock title="模型与工具" bgClass={highlightGroupBg} borderClass={highlightGroupBorder} headerClass={highlightGroupHeader} contentClass="grid grid-cols-2 gap-2 p-2">
                    <BaseBlock title="LLM Provider 
 集团 | 寿险 | 证券" className="text-[10px]" />
                    <BaseBlock title="Tool | MCP
 平台知识库工具 | 寿险数据 | 养老险数据" className="text-[10px]" />
                  </GroupBlock>

                </div>

                {/* 右侧：元智能体纵栏 */}
                <div className="w-20 lg:w-24 shrink-0 flex flex-col border-l-2 border-slate-300 bg-slate-50 rounded-md py-2 px-1.5">
                  <div className="text-slate-500 font-bold text-[10px] text-center mb-2 leading-tight">
                    <EditableText text="元智能体" />
                  </div>
                  <div className="flex flex-col gap-1.5 flex-1 justify-center">
                    <BaseBlock title="Skill 管理" className="w-full text-[10px] py-1" bgClass="bg-white" borderClass="border border-slate-300" textClass="text-slate-600" />
                    <BaseBlock title="智能体管理" className="w-full text-[10px] py-1" bgClass="bg-white" borderClass="border border-slate-300" textClass="text-slate-600" />
                    <BaseBlock title="工具管理" className="w-full text-[10px] py-1" bgClass="bg-white" borderClass="border border-slate-300" textClass="text-slate-600" />
                    <BaseBlock title="Session 管理" className="w-full text-[10px] py-1" bgClass="bg-white" borderClass="border border-slate-300" textClass="text-slate-600" />
                  </div>
                </div>

              </div>
            </LayerRow>

            {/* 4. 基础
设施层（模型 + 基础设施，两行） */}
            <LayerRow label="基础
设施">
              <div className="flex flex-col gap-2 w-full">
                <div className="flex flex-row gap-2 w-full flex-wrap">
                  <BaseBlock title="基座模型 · Qwen-80B
（规划·工具·推理）" className="flex-1 min-w-[160px] text-[11px] py-2 text-slate-600" bgClass="bg-slate-100/50" borderClass="border border-slate-200" />
                  <BaseBlock title="微调模型 · Qwen3-8B/1.7B
（意图识别快路径）" className="flex-1 min-w-[160px] text-[11px] py-2 text-slate-600" bgClass="bg-slate-100/50" borderClass="border border-slate-200" />
                  <BaseBlock title="检索重排 · Embedding / Rerank 
（知识·内容·记忆）" className="flex-1 min-w-[200px] text-[11px] py-2 text-slate-600" bgClass="bg-slate-100/50" borderClass="border border-slate-200" />
                </div>
                <div className="flex flex-row gap-2 w-full flex-wrap">
                  <BaseBlock title="大模型平台" className="flex-1 min-w-[100px] font-semibold py-2 text-slate-600" bgClass="bg-slate-100/50" borderClass="border border-slate-200" />
                <BaseBlock title="赛飞平台" className="flex-1 min-w-[100px] font-semibold py-2 text-slate-600" bgClass="bg-slate-100/50" borderClass="border border-slate-200" />
                <BaseBlock title="BU私有环境" className="flex-1 min-w-[100px] font-semibold py-2 text-slate-600" bgClass="bg-slate-100/50" borderClass="border border-slate-200" />
                <BaseBlock title="数据库 · 向量数据库 " className="flex-1 min-w-[140px] font-semibold py-2 text-slate-600" bgClass="bg-slate-100/50" borderClass="border border-slate-200" />
                </div>
              </div>
            </LayerRow>

          </div>

          {/* ================= 垂直：监控/审计层（已实施，深色表严谨） ================= */}
          <div className="hidden w-20 lg:w-24 shrink-0 flex flex-col border-l-4 border-slate-500 bg-slate-700 rounded-r-lg py-3 px-2">
            <div className="text-slate-200 font-bold text-xs text-center mb-2 tracking-widest">
              <EditableText text="监控/审计" />
            </div>
            <div className="flex flex-col gap-2 flex-1 justify-center">
              <BaseBlock title="操作监控" className="w-full text-[10px] py-1.5" bgClass="bg-slate-600" borderClass="border border-slate-500" textClass="text-slate-200" />
              <BaseBlock title="Trace" className="w-full text-[10px] py-1.5" bgClass="bg-slate-600" borderClass="border border-slate-500" textClass="text-slate-200" />
              <BaseBlock title="审计日志" className="w-full text-[10px] py-1.5" bgClass="bg-slate-600" borderClass="border border-slate-500" textClass="text-slate-200" />
              <BaseBlock title="运维监控" className="w-full text-[10px] py-1.5" bgClass="bg-slate-600" borderClass="border border-slate-500" textClass="text-slate-200" />
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
