import { useState } from 'react'

interface ToolCallProps {
    call: { id: string; name: string; arguments: Record<string, unknown> }
    result?: { tool_call_id: string; content: unknown; is_error?: boolean } | null
}

export default function ToolCallCard({ call, result }: ToolCallProps) {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="chat-tool-call" style={{ marginTop: 6 }}>
            <button type="button" className="chat-tool-header" onClick={() => setExpanded(!expanded)}>
                <span className="chat-tool-icon">{result?.is_error ? '\u26A0' : '\u2699'}</span>
                <span className="chat-tool-name">{call.name}</span>
                {result != null && (
                    <span className={result.is_error ? 'tool-result-error' : 'tool-result-ok'}>
                        {result.is_error ? 'error' : 'ok'}
                    </span>
                )}
                <span className="chat-tool-toggle">{expanded ? '\u25B2' : '\u25BC'}</span>
            </button>
            {expanded && (
                <div className="chat-tool-body">
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>Arguments</div>
                    <pre className="chat-tool-pre">{JSON.stringify(call.arguments, null, 2)}</pre>
                    {result != null && (
                        <>
                            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>Result</div>
                            <pre className={`chat-tool-pre ${result.is_error ? 'tool-result-error-bg' : ''}`}>
                                {typeof result.content === 'string' ? result.content : JSON.stringify(result.content, null, 2)}
                            </pre>
                        </>
                    )}
                </div>
            )}
        </div>
    )
}
