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
export type Order = S['OrderResponse']
export type Reservation = S['ReservationResponse']
export type OrderMaterial = S['OrderMaterialResponse']
export type Operation = S['OperationResponse']
export type Operations = S['OperationsResponse']
export type Product = S['ProductResponse']
export type ProgressResult = S['ProgressResponse']
export type OrderStatus = S['OrderStatus']
export type Bom = S['BomResponse']
export type Explosion = S['ExplodeResponse']
export type Routing = S['RoutingResponse']
export type Material = S['MaterialResponse']
export type WorkCenter = S['WorkCenterResponse']
export type LedgerLine = S['TransactionResponse']
export type Movement = S['MovementResponse']
export type AuditLog = S['AuditLogResponse']
export type AuditAction = S['AuditAction']
export type AuditEntity = S['AuditEntity']
export type OperationType = S['OperationType']

export type Page<T> = { items: T[]; total: number }

/** B13 error body. */
export type ApiErrorBody = {
  error: { code: string; message: string; details: unknown[]; request_id: string }
}
