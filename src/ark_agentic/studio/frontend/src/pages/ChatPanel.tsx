import { useEffect, useRef, useState } from 'react'
import { streamChat } from '../api'

interface ChatMessage {
    id: string
    role: 'user' | 'assistant' | 'tool'
    content: string
    toolName?: string
    toolArgs?: Record<string, unknown>
    toolResult?: unknown
    isStreaming?: boolean
    isError?: boolean
}

interface Props {
    agentId: string   // target_agent context injected into meta-builder
}

let _msgCounter = 0
const nextId = () => `msg-${++_msgCounter}`

export default function ChatPanel({ agentId }: Props) {
    const [messages, setMessages] = useState<ChatMessage[]>([{
        id: nextId(),
        role: 'assistant',
        content: `你好！我是 Ark-Agentic Meta-Agent。\n\n你可以用自然语言让我帮你：\n- 创建新的 Skill（例如：**"帮我给当前 Agent 加上退保拦截的技能"**）\n- 生成 Tool 脚手架（例如：**"生成一个查询保单状态的工具"**）\n- 创建全新的 Agent（例如：**"帮我建一个客服场景的 Agent"**）`,
    }])
    const [input, setInput] = useState('')
    const [isStreaming, setIsStreaming] = useState(false)
    const [sessionId, setSessionId] = useState<string | undefined>()
    const bottomRef = useRef<HTMLDivElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages])

    async function sendMessage() {
        const text = input.trim()
        if (!text || isStreaming) return

        const userMsg: ChatMessage = { id: nextId(), role: 'user', content: text }
        const assistantMsgId = nextId()
        const assistantMsg: ChatMessage = { id: assistantMsgId, role: 'assistant', content: '', isStreaming: true }

        setMessages(prev => [...prev, userMsg, assistantMsg])
        setInput('')
        setIsStreaming(true)

        try {
            const gen = streamChat({
                agent_id: 'meta-builder',
                message: text,
                session_id: sessionId,
                context: { 'target_agent': agentId },
            })

            for await (const event of gen) {
                if (event.type === 'run_started' && !sessionId) {
                    setSessionId(event.session_id)
                }
                if (event.type === 'text_message_content' && event.delta) {
                    setMessages(prev => prev.map(m =>
                        m.id === assistantMsgId
                            ? { ...m, content: m.content + event.delta }
                            : m
                    ))
                }
                if (event.type === 'tool_call_args' && event.tool_name) {
                    const toolMsgId = nextId()
                    setMessages(prev => [...prev.slice(0, -1), {
                        id: toolMsgId,
                        role: 'tool',
                        content: '',
                        toolName: event.tool_name,
                        toolArgs: event.tool_args,
                    }, prev[prev.length - 1]])
                }
                if (event.type === 'tool_call_result') {
                    setMessages(prev => prev.map(m =>
                        m.role === 'tool' && m.toolName === event.tool_name && m.toolResult === undefined
                            ? { ...m, toolResult: event.tool_result }
                            : m
                    ))
                }
                if (event.type === 'run_finished') {
                    setMessages(prev => prev.map(m =>
                        m.id === assistantMsgId ? { ...m, isStreaming: false } : m
                    ))
                }
                if (event.type === 'run_error') {
                    setMessages(prev => prev.map(m =>
                        m.id === assistantMsgId
                            ? { ...m, content: `❌ ${event.error_message}`, isStreaming: false, isError: true }
                            : m
                    ))
                }
            }
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err)
            setMessages(prev => prev.map(m =>
                m.id === assistantMsgId
                    ? { ...m, content: `❌ 连接失败：${msg}`, isStreaming: false, isError: true }
                    : m
            ))
        } finally {
            setIsStreaming(false)
        }
    }

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            sendMessage()
        }
    }

    return (
        <div className="chat-panel">
            <div className="chat-history">
                {messages.map(msg => (
                    <div key={msg.id} className={`chat-message chat-message-${msg.role}`}>
                        {msg.role === 'tool' ? (
                            <ToolCallBlock
                                toolName={msg.toolName!}
                                toolArgs={msg.toolArgs}
                                toolResult={msg.toolResult}
                            />
                        ) : (
                            <div className={`chat-bubble${msg.isError ? ' chat-bubble-error' : ''}`}>
                                <MessageContent content={msg.content} />
                                {msg.isStreaming && <span className="chat-cursor" />}
                            </div>
                        )}
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>

            <div className="chat-input-area">
                <textarea
                    ref={textareaRef}
                    className="chat-input-box"
                    rows={2}
                    placeholder={isStreaming ? '正在处理中…' : '输入消息，按 Enter 发送（Shift+Enter 换行）'}
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={isStreaming}
                />
                <button
                    className="btn btn-primary chat-send-btn"
                    onClick={sendMessage}
                    disabled={isStreaming || !input.trim()}
                >
                    {isStreaming ? '…' : '发送'}
                </button>
            </div>
        </div>
    )
}

// ── Sub-components ───────────────────────────────────────────────

function ToolCallBlock({ toolName, toolArgs, toolResult }: {
    toolName: string
    toolArgs?: Record<string, unknown>
    toolResult?: unknown
}) {
    const [open, setOpen] = useState(false)
    return (
        <div className="chat-tool-call">
            <button className="chat-tool-header" onClick={() => setOpen(o => !o)}>
                <span className="chat-tool-icon">⚙️</span>
                <span className="chat-tool-name">{toolName}</span>
                <span className="chat-tool-result-badge">
                    {toolResult !== undefined ? '✅ 完成' : '⏳ 执行中'}
                </span>
                <span className="chat-tool-toggle">{open ? '▲' : '▼'}</span>
            </button>
            {open && (
                <div className="chat-tool-body">
                    {toolArgs && (
                        <pre className="chat-tool-pre">{JSON.stringify(toolArgs, null, 2)}</pre>
                    )}
                    {toolResult !== undefined && (
                        <div className="chat-tool-result">
                            <strong>结果：</strong>
                            <span>{String(toolResult)}</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

/** Render plain text with line-break support (no heavy markdown lib). */
function MessageContent({ content }: { content: string }) {
    return (
        <>{content.split('\n').map((line, i) => (
            <span key={i}>
                {i > 0 && <br />}
                {line}
            </span>
        ))}</>
    )
}
