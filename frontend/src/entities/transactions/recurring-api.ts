import { apiGet, apiPost } from "@shared/api/http";

export type RecurringState = "enabled" | "disabled" | "pending" | "retrying" | "attention";

export const RECURRING_STATES: readonly RecurringState[] = ["attention", "pending", "retrying", "enabled", "disabled"];

const RECURRING_PAGE_SIZE = 25;

export interface RecurringPaymentItem {
  subscription_id: number;
  user_id: number;
  user_name: string | null;
  plan_name: string;
  enabled: boolean;
  customer_disabled: boolean;
  state: RecurringState;
  last_error: string | null;
  next_attempt_at: string | null;
  submitted_at: string | null;
  pending_transaction_id: number | null;
  external_payment_id: string | null;
  can_check: boolean;
  can_close: boolean;
  can_retry: boolean;
  retry_count: number;
  first_failure_at: string | null;
  amount_limit: string | null;
  currency: string | null;
  duration_days: number | null;
  has_saved_method: boolean;
  expire_at: string;
}

export interface RecurringPaymentSummary {
  total: number;
  enabled: number;
  disabled: number;
  pending: number;
  retrying: number;
  attention: number;
  paid_renewals: number;
  failed_renewals: number;
  revenue: string;
  currency: string;
}

export interface RecurringPaymentPage {
  items: RecurringPaymentItem[];
  total: number;
}

export interface RecurringConsent {
  channel: "BOT" | "CABINET";
  accepted_at: string;
  revoked_at: string | null;
  revoked_channel: string | null;
  terms: { text: string; amount_limit: string; currency: string; duration_days: number; max_overdue_hours: number };
}

export type RecurringAction = "check" | "close" | "retry";

export function listRecurringPayments(
  state: RecurringState | null,
  search: string,
  page: number,
  signal?: AbortSignal,
): Promise<RecurringPaymentPage> {
  const query = new URLSearchParams({ page: String(page), page_size: String(RECURRING_PAGE_SIZE) });
  if (state) query.set("state", state);
  if (search) query.set("search", search);
  return apiGet<RecurringPaymentPage>(`/transactions/recurring?${query.toString()}`, signal);
}

export function getRecurringPaymentSummary(signal?: AbortSignal): Promise<RecurringPaymentSummary> {
  return apiGet<RecurringPaymentSummary>("/transactions/recurring/summary", signal);
}

export function getRecurringConsent(subscriptionId: number, signal?: AbortSignal): Promise<RecurringConsent> {
  return apiGet<RecurringConsent>(`/transactions/recurring/${subscriptionId}/consent`, signal);
}

export function runRecurringAction(
  subscriptionId: number,
  action: RecurringAction,
  expectedPendingId: number | null,
): Promise<void> {
  return apiPost<void, { expected_pending_transaction_id: number | null }>(
    `/transactions/recurring/${subscriptionId}/actions/${action}`,
    { expected_pending_transaction_id: expectedPendingId },
  );
}
