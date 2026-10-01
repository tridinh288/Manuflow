// Types come from the backend's OpenAPI schema (B2); never hand-written.
import type { components } from './schema'

type S = components['schemas']

export type Me = S['MeResponse']
export type Token = S['TokenResponse']
export type ProductionOverview = S['ProductionOverviewResponse']
export type OrderRisk = S['OrderRiskResponse']
export type Bottleneck = S['BottleneckResponse']
export type MaterialAlerts = S['MaterialAlertsResponse']
export type Balance = S['BalanceResponse']
export type OrderSummary = S['OrderSummary']

export type Page<T> = { items: T[]; total: number }

/** B13 error body. */
export type ApiErrorBody = {
  error: { code: string; message: string; details: unknown[]; request_id: string }
}
