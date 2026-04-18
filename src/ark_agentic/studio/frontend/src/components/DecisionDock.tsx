import { useEffect, useMemo, useRef, useState } from 'react'
import { streamChat, type AgentMeta } from '../api'
import { SparkIcon, TraceIcon } from './StudioIcons'

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
  selectedAgent: AgentMeta | null
  visible: boolean
}

let nextMessageSeed = 0
function nextMessageId() {
  nextMessageSeed += 1
  return `dock-msg-${nextMessageSeed}`
}

function initialAssistantMessage(agentName?: string): DockMessage {
  const target = agentName ? `当前目标 Agent 是 ${agentName}。` : '你可以先从左侧选择一个 Agent。'
  return {
    id: nextMessageId(),
    role: 'assistant',
    content: `Meta-Agent 已进入决策辅助模式。${target}\n我会把建议聚焦在变更影响、复核要点和可验证动作上。`,
  }
}

export default function DecisionDock({ activeSection, selectedAgent, visible }: DecisionDockProps) {
  const [messages, setMessages] = useState<DockMessage[]>(() => [initialAssistantMessage()])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId, setSessionId] = useState<string | undefined>()
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
    setMessages([initialAssistantMessage(selectedAgent?.name)])
    setSessionId(undefined)
    setInput('')
  }, [selectedAgent?.id])

  const summaryCards = useMemo(() => {
    return [
      {
        title: 'Context',
        body: selectedAgent ? `${selectedAgent.name} · ${activeSection}` : 'No agent selected',
      },
      {
        title: 'Mode',
        body: 'AI suggests changes, humans review and execute directly',
      },
    ]
  }, [activeSection, selectedAgent])

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
    setMessages([initialAssistantMessage(selectedAgent?.name)])
  }

  return (
    <aside className={`decision-dock ${visible ? '' : 'decision-dock-hidden'}`}>
      <div className="decision-dock-header">
        <div>
          <div className="decision-dock-eyebrow">
            <SparkIcon />
            Meta-Agent Decision Dock
          </div>
          <h2>{selectedAgent ? selectedAgent.name : 'Select an agent'}</h2>
        </div>
        <button className="dock-button dock-button-ghost" onClick={startFreshSession} type="button">
          New Session
        </button>
      </div>

      <div className="decision-dock-summary">
        {summaryCards.map(card => (
          <div className="dock-summary-card" key={card.title}>
            <span>{card.title}</span>
            <strong>{card.body}</strong>
          </div>
        ))}
      </div>

      <div className="decision-dock-guidance">
        <TraceIcon />
        <p>
          Ask for concrete changes, impact analysis, review notes, or follow-up actions.
          The dock is designed to drive edits, not idle conversation.
        </p>
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
              ? 'Describe the next change or ask for an impact review...'
              : 'Select an agent to activate the dock'
          }
          rows={4}
          value={input}
        />
        <button
          className="dock-button dock-button-primary"
          disabled={!selectedAgent || !input.trim() || isStreaming}
          onClick={() => void sendMessage()}
          type="button"
        >
          {isStreaming ? 'Working...' : 'Send to Meta-Agent'}
        </button>
      </div>
    </aside>
  )
}
