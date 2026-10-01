import { useState } from 'react'

import { api, idem } from '../api/client'
import type { OrderMaterial } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { useSubmit } from '../lib/useSubmit'
import { ErrorBox } from './ErrorBox'

/** ISSUE / RETURN for one order line; the server checks D-10 and the returnable amount. */
export function MoveStock({ line, onDone }: { line: OrderMaterial; onDone: () => void }) {
  const { can } = useAuth()
  const [quantity, setQuantity] = useState('')
  const move = useSubmit(async ({ kind, qty }: { kind: 'issues' | 'returns'; qty: string }, key: string) => {
    const response = await api.post(
      `/inventory/${kind}`,
      { order_material_id: line.id, quantity: qty },
      idem(key),
    )
    return response.data as unknown
  })

  async function send(kind: 'issues' | 'returns', qty: string) {
    if ((await move.submit({ kind, qty })) !== undefined) {
      setQuantity('')
      onDone()
    }
  }

  return (
    <div className="row">
      <input
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        placeholder={line.reserved_quantity}
        aria-label={`Số lượng ${line.material_code}`}
        size={8}
      />
      {can('inventory:issue') && (
        <button disabled={move.busy} onClick={() => send('issues', quantity || line.reserved_quantity)}>
          Xuất
        </button>
      )}
      {can('inventory:return') && (
        <button disabled={move.busy || !quantity} onClick={() => send('returns', quantity)}>
          Trả
        </button>
      )}
      <ErrorBox error={move.error} />
    </div>
  )
}
