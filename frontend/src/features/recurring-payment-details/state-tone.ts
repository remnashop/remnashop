import type { RecurringState } from "@entities/transactions/recurring-api";
import type { BadgeTone } from "@shared/ui/Badge";

export const RECURRING_STATE_TONE: Record<RecurringState, BadgeTone> = {
  enabled: "success",
  disabled: "neutral",
  pending: "warning",
  retrying: "accent",
  attention: "error",
};
