/** Display helpers only: values are shown as the API sent them, never recomputed. */
export function formatDate(value: string): string {
  return new Date(value).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })
}

/** API ratios (0..1, already rounded to 2 places by the server) as a percentage label. */
export function percent(ratio: number | null | undefined): string {
  return ratio === null || ratio === undefined ? '—' : `${Math.round(ratio * 100)}%`
}
