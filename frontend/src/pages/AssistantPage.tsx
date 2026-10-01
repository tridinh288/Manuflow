import { useState } from 'react'
import type { FormEvent } from 'react'

import { api, idem } from '../api/client'
import type { AssistantAnswer, AssistantStatus } from '../api/types'
import { ErrorBox } from '../components/ErrorBox'
import { useApi } from '../lib/useApi'
import { useSubmit } from '../lib/useSubmit'

type Turn = { question: string; reply: AssistantAnswer }

/**
 * Phase 9 (B17): questions answered by read-only tools run as the current user. The page
 * shows which tools ran and warns when the answer quotes numbers no tool returned
 * (BR-AI-03); it never changes data (BR-AI-04).
 */
export function AssistantPage() {
  const status = useApi<AssistantStatus>('/assistant/status')
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const ask = useSubmit(async (q: string, key: string) =>
    (await api.post<AssistantAnswer>('/assistant/ask', { question: q }, idem(key))).data,
  )

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const asked = question.trim()
    const reply = await ask.submit(asked)
    if (reply) {
      setTurns((current) => [{ question: asked, reply }, ...current])
      setQuestion('')
    }
  }

  if (status.error) return <ErrorBox error={status.error} />
  if (status.data && !status.data.enabled) {
    return (
      <div className="stack">
        <h1>Trợ lý</h1>
        <section>
          <p className="muted">
            Trợ lý chưa được bật trên máy chủ này (cần <code>ASSISTANT_API_KEY</code>).
          </p>
        </section>
      </div>
    )
  }

  return (
    <div className="stack">
      <h1>Trợ lý</h1>
      <section>
        <form className="row" onSubmit={onSubmit}>
          <label style={{ flex: 1 }}>
            Câu hỏi
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Tuần này có làm được 150 FRAME-A không?"
              maxLength={1000}
              required
            />
          </label>
          <button className="primary" disabled={ask.busy}>
            {ask.busy ? 'Đang tra cứu…' : 'Hỏi'}
          </button>
        </form>
        <ErrorBox error={ask.error} />
        {status.data && (
          <p className="muted">
            Chỉ đọc dữ liệu, theo quyền của bạn. Công cụ: {status.data.tools.join(', ')}.
          </p>
        )}
      </section>
      {turns.map((turn, index) => (
        <section key={turns.length - index}>
          <h2>{turn.question}</h2>
          <p style={{ whiteSpace: 'pre-wrap' }}>{turn.reply.answer}</p>
          {!turn.reply.grounded && (
            <div className="error" role="status">
              Câu trả lời có số không có trong dữ liệu tra cứu: {turn.reply.ungrounded_numbers.join(', ')}. Hãy kiểm tra
              lại trên các trang tương ứng.
            </div>
          )}
          <details>
            <summary className="muted">Đã tra cứu {turn.reply.tool_calls.length} lần</summary>
            <ul>
              {turn.reply.tool_calls.map((call, i) => (
                <li key={i}>
                  <code>{call.name}</code> {JSON.stringify(call.arguments)}{' '}
                  {call.ok ? '✓' : `✗ ${String((call.result.error as { code?: string } | undefined)?.code ?? '')}`}
                </li>
              ))}
            </ul>
          </details>
        </section>
      ))}
    </div>
  )
}
