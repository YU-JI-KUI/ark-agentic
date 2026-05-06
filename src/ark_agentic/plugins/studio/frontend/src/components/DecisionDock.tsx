import { useEffect, useRef, useState } from 'react'
import { streamChat, type AgentMeta } from '../api'
import { CloseIcon, PlusIcon, SendIcon, SparkIcon } from './StudioIcons'

interface DockMessage {
  id: string
  role: 'assistant' | 'user' | 'tool'
  content: string
  toolName?: string
  toolArgs?: Record<string, unknown>
  toolResult?: unknown
  isStreaming?: boolean
  isError?: boolean
}

interface DecisionDockProps {
  activeSection: string
  maxWidth: number
  minWidth: number
  onClose: () => void
  onWidthChange: (width: number) => void
  selectedAgent: AgentMeta | null
  visible: boolean
  width: number
}

let nextMessageSeed = 0
function nextMessageId() {
  nextMessageSeed += 1
  return `dock-msg-${nextMessageSeed}`
}

function initialAssistantMessage(): DockMessage {
  return {
    id: nextMessageId(),
    role: 'assistant',
    content:
      '你好！我是 Ark-Agentic Meta-Agent。\n\n你可以用自然语言让我帮你：\n- 创建新的 Skill（例如：帮我给当前 Agent 加上退休拦截的技能）\n- 生成 Tool 脚手架（例如：生成一个查询保单状态的工具）\n- 创建全新的 Agent（例如：帮我建一个客服场景的 Agent）',
  }
}

export default function DecisionDock({
  activeSection,
  maxWidth,
  minWidth,
  onClose,
  onWidthChange,
  selectedAgent,
  visible,
  width,
}: DecisionDockProps) {
  const [messages, setMessages] = useState<DockMessage[]>(() => [initialAssistantMessage()])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [isResizing, setIsResizing] = useState(false)
  const resizeRef = useRef<{ startWidth: number; startX: number } | null>(null)
  const streamRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const stream = streamRef.current
    if (!stream) return
    stream.scrollTo({
      top: stream.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  useEffect(() => {
    setMessages([initialAssistantMessage()])
    setSessionId(undefined)
    setInput('')
  }, [selectedAgent?.id])

  useEffect(() => {
    if (!isResizing) return

    function handlePointerMove(event: PointerEvent) {
      const current = resizeRef.current
      if (!current) return
      const delta = current.startX - event.clientX
      const nextWidth = Math.min(maxWidth, Math.max(minWidth, current.startWidth + delta))
      onWidthChange(nextWidth)
    }

    function stopResizing() {
      resizeRef.current = null
      setIsResizing(false)
      document.body.style.removeProperty('cursor')
      document.body.style.removeProperty('user-select')
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopResizing)
    window.addEventListener('pointercancel', stopResizing)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopResizing)
      window.removeEventListener('pointercancel', stopResizing)
      document.body.style.removeProperty('cursor')
      document.body.style.removeProperty('user-select')
    }
  }, [isResizing, maxWidth, minWidth, onWidthChange])

  async function sendMessage() {
    const text = input.trim()
    if (!text || !selectedAgent || isStreaming) return

    const userMessage: DockMessage = { id: nextMessageId(), role: 'user', content: text }
    const assistantId = nextMessageId()
    const assistantMessage: DockMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      isStreaming: true,
    }

    setMessages(prev => [...prev, userMessage, assistantMessage])
    setInput('')
    setIsStreaming(true)

    try {
      const generator = streamChat({
        agent_id: 'meta_builder',
        message: text,
        session_id: sessionId,
        context: {
          target_agent: selectedAgent.id,
          target_surface: activeSection,
        },
      })

      for await (const event of generator) {
        if (event.type === 'run_started' && event.session_id && !sessionId) {
          setSessionId(event.session_id)
        }
        if (event.type === 'text_message_content' && event.delta) {
          setMessages(prev =>
            prev.map(message =>
              message.id === assistantId
                ? { ...message, content: message.content + event.delta }
                : message,
            ),
          )
        }
        if ((event.type === 'tool_call_start' || event.type === 'tool_call_args') && event.tool_name) {
          const toolId = nextMessageId()
          setMessages(prev => [
            ...prev.slice(0, -1),
            {
              id: toolId,
              role: 'tool',
              content: '',
              toolName: event.tool_name,
              toolArgs: event.tool_args,
            },
            prev[prev.length - 1],
          ])
        }
        if (event.type === 'tool_call_result') {
          setMessages(prev =>
            prev.map(message =>
              message.role === 'tool' &&
              message.toolName === event.tool_name &&
              message.toolResult === undefined
                ? { ...message, toolResult: event.tool_result }
                : message,
            ),
          )
        }
        if (event.type === 'run_finished') {
          setMessages(prev =>
            prev.map(message =>
              message.id === assistantId ? { ...message, isStreaming: false } : message,
            ),
          )
        }
        if (event.type === 'run_error') {
          setMessages(prev =>
            prev.map(message =>
              message.id === assistantId
                ? {
                    ...message,
                    content: event.error_message ?? 'Meta-Agent failed to complete the request.',
                    isStreaming: false,
                    isError: true,
                  }
                : message,
            ),
          )
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setMessages(prev =>
        prev.map(item =>
          item.id === assistantId
            ? {
                ...item,
                content: `Connection failed: ${message}`,
                isStreaming: false,
                isError: true,
              }
            : item,
        ),
      )
    } finally {
      setIsStreaming(false)
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  function startFreshSession() {
    if (isStreaming) return
    setSessionId(undefined)
    setMessages([initialAssistantMessage()])
  }

  function handleResizeStart(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return
    resizeRef.current = { startWidth: width, startX: event.clientX }
    setIsResizing(true)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  return (
    <aside
      className={`decision-dock ${visible ? '' : 'decision-dock-hidden'} ${isResizing ? 'decision-dock-resizing' : ''}`}
    >
      <button
        aria-label="Resize Meta-Agent dock"
        className="decision-dock-resize-handle"
        onPointerDown={handleResizeStart}
        type="button"
      />
      <div className="decision-dock-header">
        <div>
          <div className="decision-dock-eyebrow">
            <SparkIcon />
            Meta-Agent (Builder)
          </div>
        </div>
        <div className="decision-dock-controls">
          <button
            aria-label="Start new Meta-Agent session"
            className="dock-icon-button"
            onClick={startFreshSession}
            title="New Session"
            type="button"
          >
            <PlusIcon />
          </button>
          <button
            aria-label="Hide Meta-Agent dock"
            className="dock-icon-button"
            onClick={onClose}
            type="button"
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      <div className="decision-dock-stream" ref={streamRef}>
        {messages.map(message => (
          <article
            className={`dock-message dock-message-${message.role} ${message.isError ? 'dock-message-error' : ''}`}
            key={message.id}
          >
            {message.role === 'tool' ? (
              <div className="dock-tool-card">
                <div className="dock-tool-title">{message.toolName}</div>
                {message.toolArgs && (
                  <pre className="dock-code-block">{JSON.stringify(message.toolArgs, null, 2)}</pre>
                )}
                {message.toolResult !== undefined && (
                  <pre className="dock-code-block">{String(message.toolResult)}</pre>
                )}
              </div>
            ) : (
              <>
                <span className="dock-message-role">{message.role}</span>
                <div className="dock-message-body">
                  {message.content.split('\n').map((line, index) => (
                    <span key={`${message.id}-${index}`}>
                      {index > 0 && <br />}
                      {line}
                    </span>
                  ))}
                  {message.isStreaming && <span className="dock-cursor" />}
                </div>
              </>
            )}
          </article>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="decision-dock-composer">
        <textarea
          className="dock-textarea"
          disabled={!selectedAgent || isStreaming}
          onChange={event => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            selectedAgent
              ? '输入消息，按 Enter 发送'
              : '请先选择一个 Agent'
          }
          rows={3}
          value={input}
        />
        <button
          aria-label={isStreaming ? 'Sending' : 'Send to Meta-Agent'}
          className="dock-send-button"
          disabled={!selectedAgent || !input.trim() || isStreaming}
          onClick={() => void sendMessage()}
          title={isStreaming ? 'Sending…' : 'Send'}
          type="button"
        >
          <SendIcon />
        </button>
      </div>
    </aside>
  )
}
