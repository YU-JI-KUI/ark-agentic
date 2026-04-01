import { useState } from 'react'
import type { MessageItem } from '../api'
import ToolCallCard from './ToolCallCard'

interface Props {
    msg: MessageItem
    index: number
    messages: MessageItem[]
}

export default function MessageBlock({ msg, index, messages }: Props) {
    const [expandThinking, setExpandThinking] = useState(false)
    const [expandMeta, setExpandMeta] = useState(false)
    const [expandResults, setExpandResults] = useState(false)

    const role = msg.role
    const roleLabel = role === 'user' ? 'User' : role === 'assistant' ? 'Assistant' : role === 'tool' ? 'Tool' : role
    const blockClass = `msg-block msg-block-${role === 'user' ? 'user' : role === 'assistant' ? 'assistant' : 'tool'}`

    const resultMap = new Map<string, { tool_call_id: string; content: unknown; is_error?: boolean }>()
    if (role === 'assistant' && msg.tool_calls?.length) {
        for (let j = index + 1; j < messages.length; j++) {
            const next = messages[j]
            if (next.role !== 'tool') break
            for (const tr of next.tool_results ?? []) {
                resultMap.set(tr.tool_call_id, tr)
            }
        }
    }

    const hasToolResults = role === 'tool' && (msg.tool_results?.length ?? 0) > 0
    const isToolResultHandledByParent = role === 'tool' && index > 0 && messages[index - 1]?.role === 'assistant' && (messages[index - 1]?.tool_calls?.length ?? 0) > 0

    if (isToolResultHandledByParent) return null

    return (
        <div className={blockClass}>
            <div className="msg-role-badge">{roleLabel}</div>

            {msg.content != null && msg.content !== '' && (
                <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 6 }}>{msg.content}</div>
            )}

            {msg.tool_calls && msg.tool_calls.length > 0 && (
                <div style={{ marginTop: 8 }}>
                    {msg.tool_calls.map(tc => (
                        <ToolCallCard key={tc.id} call={tc} result={resultMap.get(tc.id)} />
                    ))}
                </div>
            )}

            {hasToolResults && !isToolResultHandledByParent && (
                <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn-action" style={{ fontSize: 12 }} onClick={() => setExpandResults(!expandResults)}>
                        {expandResults ? 'Hide' : 'Show'} results ({msg.tool_results!.length})
                    </button>
                    {expandResults && (
                        <pre className="code-block" style={{ marginTop: 4, fontSize: 12 }}>
                            {JSON.stringify(msg.tool_results, null, 2)}
                        </pre>
                    )}
                </div>
            )}

            {msg.thinking && (
                <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn-action" style={{ fontSize: 12 }} onClick={() => setExpandThinking(!expandThinking)}>
                        {expandThinking ? 'Hide' : 'Show'} thinking
                    </button>
                    {expandThinking && (
                        <pre className="code-block" style={{ marginTop: 4, fontSize: 12, background: 'var(--color-bg)' }}>{msg.thinking}</pre>
                    )}
                </div>
            )}

            {msg.metadata && Object.keys(msg.metadata).length > 0 && (
                <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn-action" style={{ fontSize: 12 }} onClick={() => setExpandMeta(!expandMeta)}>
                        {expandMeta ? 'Hide' : 'Show'} metadata
                    </button>
                    {expandMeta && (
                        <pre className="code-block" style={{ marginTop: 4, fontSize: 12 }}>{JSON.stringify(msg.metadata, null, 2)}</pre>
                    )}
                </div>
            )}

            {!msg.content && !msg.tool_calls?.length && !hasToolResults && !msg.thinking && (
                <span style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>&mdash;</span>
            )}
        </div>
    )
}
