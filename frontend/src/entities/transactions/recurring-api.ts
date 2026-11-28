import { apiGet, apiPost } from "@shared/api/http";
import type { ApiSchema } from "@shared/api/schemas";
import { allValues } from "@shared/lib/all-values";

export type RecurringState = ApiSchema<"RecurringState">;

export const RECURRING_STATES = allValues<RecurringState>()(["attention", "pending", "retrying", "enabled", "disabled"]);

const RECURRING_PAGE_SIZE = 25;

export type RecurringPaymentItem = ApiSchema<"RecurringPaymentAdminItemResponse">;

export type RecurringPaymentSummary = ApiSchema<"RecurringPaymentSummaryResponse">;

type RecurringPaymentPage = ApiSchema<"RecurringPaymentPageResponse">;

export type RecurringConsent = ApiSchema<"RecurringConsentResponse">;

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
  return apiPost<void, ApiSchema<"RecurringAdminActionRequest">>(
    `/transactions/recurring/${subscriptionId}/actions/${action}`,
    { expected_pending_transaction_id: expectedPendingId },
  );
}
