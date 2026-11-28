import type { ParseKeys } from "i18next";
import { AlertTriangle, Ban, Check, ChevronRight, Clock, Filter, RefreshCw, Repeat, Wallet } from "lucide-react";
import { useMemo, useState, type ComponentType } from "react";
import { useTranslation } from "react-i18next";

import {
  getRecurringPaymentSummary,
  listRecurringPayments,
  RECURRING_STATES,
  type RecurringPaymentItem,
  type RecurringState,
} from "@entities/transactions/recurring-api";
import { usePermissions } from "@entities/user/use-current-user";
import { RecurringPaymentDialog } from "@features/recurring-payment-details/RecurringPaymentDialog";
import { RECURRING_STATE_TONE } from "@features/recurring-payment-details/state-tone";
import { formatMoney } from "@shared/lib/format";
import { LoadGate } from "@shared/lib/load-gate";
import { formatDate, formatDateTime } from "@shared/lib/relative-time";
import { useAsyncResource } from "@shared/lib/use-async-resource";
import { useDebouncedValue } from "@shared/lib/use-debounced-value";
import { usePaginatedList } from "@shared/lib/use-paginated-list";
import { AnimatedHeight } from "@shared/ui/glass/AnimatedHeight";
import { EmptyState, ErrorState } from "@shared/ui/glass/EmptyState";
import { IconCircle } from "@shared/ui/glass/IconCircle";
import { KpiTile } from "@shared/ui/KpiTile";
import { ListRow } from "@shared/ui/ListRow";
import { LoadMoreButton } from "@shared/ui/LoadMoreButton";
import { SearchField } from "@shared/ui/SearchField";
import { SelectDropdown } from "@shared/ui/SelectDropdown";
import { RefetchSpinner, Spinner } from "@shared/ui/Spinner";
import { LIST_BODY_CLASS, LIST_SCROLL_X_CLASS, PAGE_BAR_CLASS, PAGE_CLASS, PAGE_SCROLL_UNDER_BAR_CLASS, PAGE_TOOLBAR_SEARCH_CLASS } from "@shared/ui/classes";
import { TransactionsTabs } from "@pages/transactions/TransactionsTabs";

const FILTER_DEBOUNCE_MS = 300;

const ROW_GRID_CLASSNAME = "grid grid-cols-[32px_minmax(0,1fr)_96px_minmax(0,1.3fr)_150px_16px] items-center gap-3";

const STATE_ICONS: Record<RecurringState, ComponentType<{ className?: string }>> = {
  attention: AlertTriangle,
  pending: Clock,
  retrying: RefreshCw,
  enabled: Check,
  disabled: Ban,
};

export function RecurringPaymentsPage() {
  const { t, i18n } = useTranslation();
  const permissions = usePermissions();
  const canViewSummary = permissions.includes("TRANSACTIONS_RECURRING_SUMMARY_VIEW");
  const [state, setState] = useState<RecurringState | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput, FILTER_DEBOUNCE_MS).trim();
  const [opened, setOpened] = useState<RecurringPaymentItem | null>(null);

  const filters = useMemo(() => ({ state, search }), [state, search]);
  const { state: list, isFetching, isLoadingMore, hasMore, loadMore, reload } = usePaginatedList(
    (current, page, signal) => listRecurringPayments(current.state, current.search, page, signal),
    filters,
    (item) => item.subscription_id,
  );
  const [summaryState, reloadSummary] = useAsyncResource((signal) =>
    canViewSummary ? getRecurringPaymentSummary(signal) : Promise.resolve(null),
  );
  const summary = summaryState.kind === "ready" ? summaryState.data : null;
  const none = t("common.none");
  const count = (value: number) => value.toLocaleString(i18n.language);

  return (
    <div data-fills-main className={PAGE_CLASS}>
      <div className={`${PAGE_BAR_CLASS} flex flex-wrap items-center gap-5 md:flex-nowrap`}>
        <TransactionsTabs active="recurring" />
        {/* filters share one glass strip beside the tabs */}
        <div className="glass-panel flex min-w-0 flex-1 flex-wrap items-center gap-2 rounded-3xl p-1.5 md:flex-nowrap">
          <div className="min-w-40 flex-1 md:w-60 md:flex-none">
            <SelectDropdown
              id="recurring-state"
              value={state ?? ""}
              onChange={(value) => setState(value === "" ? null : (value as RecurringState))}
              icon={Filter}
              size="compact"
              glassPopover
              placeholder={t("transactions.filters.statusAll")}
              options={[
                { value: "", label: t("transactions.filters.statusAll"), icon: Filter },
                ...RECURRING_STATES.map((value) => ({
                  value,
                  label: t(`transactions.recurring.states.${value}`),
                  icon: STATE_ICONS[value],
                })),
              ]}
            />
          </div>
          <div className={PAGE_TOOLBAR_SEARCH_CLASS}>
            <SearchField
              id="recurring-search"
              placeholder={t("transactions.recurring.searchPlaceholder")}
              value={searchInput}
              onChange={setSearchInput}
            />
          </div>
        </div>
      </div>

      <div className={`${PAGE_SCROLL_UNDER_BAR_CLASS} flex flex-col gap-5`}>
        <LoadGate>
          <div className="flex flex-col gap-5">
            {summary && (
              <div className="grid shrink-0 grid-cols-2 gap-5 lg:grid-cols-4">
                <KpiTile
                  panel
                  icon={Repeat}
                  label={t("transactions.recurring.kpi.enabled")}
                  value={count(summary.enabled)}
                  valueSuffix={t("transactions.recurring.kpi.ofTotal", { total: count(summary.total) })}
                  hint={t("transactions.recurring.kpi.disabled", { count: summary.disabled })}
                />
                <KpiTile
                  panel
                  icon={AlertTriangle}
                  label={t("transactions.recurring.kpi.attention")}
                  value={count(summary.attention)}
                  hint={t("transactions.recurring.kpi.inProgress", {
                    pending: count(summary.pending),
                    retrying: count(summary.retrying),
                  })}
                />
                <KpiTile
                  panel
                  icon={Check}
                  label={t("transactions.recurring.kpi.paid")}
                  value={count(summary.paid_renewals)}
                  hint={t("transactions.recurring.kpi.failed", { count: summary.failed_renewals })}
                />
                <KpiTile
                  panel
                  icon={Wallet}
                  label={t("transactions.recurring.kpi.revenue")}
                  value={formatMoney(summary.revenue, summary.currency, i18n.language)}
                  hint={t("transactions.recurring.kpi.allTime")}
                />
              </div>
            )}

            <div className="glass-panel relative shrink-0 rounded-3xl p-4">
              {list.kind === "ready" && isFetching && <RefetchSpinner />}
              <AnimatedHeight>
                {list.kind === "loading" && <Spinner size="page" />}
                {list.kind === "error" && <ErrorState text={t("transactions.recurring.error")} size="page" />}
                {list.kind === "ready" && list.items.length === 0 && (
                  <EmptyState text={t("transactions.recurring.empty")} size="page" />
                )}
                {list.kind === "ready" && list.items.length > 0 && (
                  <div className={LIST_SCROLL_X_CLASS}>
                    <div className={`min-w-[760px] ${LIST_BODY_CLASS}`}>
                      {list.items.map((item) => {
                        const Icon = STATE_ICONS[item.state];
                        const next = nextLabel(item);
                        return (
                          <ListRow
                            key={item.subscription_id}
                            type="button"
                            onClick={() => setOpened(item)}
                            className={ROW_GRID_CLASSNAME}
                          >
                            <IconCircle tone={RECURRING_STATE_TONE[item.state]} icon={Icon} />
                            <span className="min-w-0">
                              <span className="flex min-w-0 items-center gap-2">
                                <span className="truncate text-sm font-medium text-foreground">{item.plan_name}</span>
                                <span className="shrink-0 font-mono text-xs text-muted-foreground">
                                  #{item.subscription_id}
                                </span>
                              </span>
                              <span className="flex min-w-0 gap-1 text-xs text-muted-foreground">
                                <span className="truncate">{item.user_name ?? none}</span>
                                <span className="shrink-0 font-mono">#{item.user_id}</span>
                              </span>
                            </span>
                            <span className="min-w-0">
                              <span className="block text-xs text-muted-foreground">{t("transactions.recurring.limit")}</span>
                              <span className="text-sm tabular-nums text-foreground">
                                {item.amount_limit && item.currency
                                  ? formatMoney(item.amount_limit, item.currency, i18n.language)
                                  : none}
                              </span>
                            </span>
                            <span className="min-w-0">
                              <span className="block truncate text-sm text-foreground">
                                {t(`transactions.recurring.states.${item.state}`)}
                              </span>
                              <span className="block truncate text-xs text-muted-foreground">
                                {item.last_error
                                  ? t(`transactions.recurring.reasons.${item.last_error}` as ParseKeys, {
                                      defaultValue: item.last_error,
                                    })
                                  : none}
                              </span>
                            </span>
                            <span className="min-w-0 text-right">
                              <span className="block text-xs text-muted-foreground">{t(next.label)}</span>
                              <span className="text-sm tabular-nums text-foreground">
                                {next.at === null
                                  ? none
                                  : next.withTime
                                    ? formatDateTime(next.at, i18n.language)
                                    : formatDate(next.at, i18n.language)}
                              </span>
                            </span>
                            <ChevronRight className="size-4 text-muted-foreground" />
                          </ListRow>
                        );
                      })}
                    </div>
                  </div>
                )}
              </AnimatedHeight>
              {list.kind === "ready" && hasMore && (
                <div className="mx-3 mt-4">
                  <LoadMoreButton
                    onClick={() => void loadMore()}
                    isLoading={isLoadingMore}
                    shown={list.items.length}
                    total={list.total}
                  />
                </div>
              )}
            </div>
          </div>
        </LoadGate>
      </div>

      {opened && (
        <RecurringPaymentDialog
          item={opened}
          onClose={() => setOpened(null)}
          onChanged={() => {
            reload();
            reloadSummary();
          }}
        />
      )}
    </div>
  );
}

function nextLabel(item: RecurringPaymentItem): { label: ParseKeys; at: string | null; withTime: boolean } {
  if (item.pending_transaction_id !== null) {
    return { label: "transactions.recurring.next.check", at: item.next_attempt_at, withTime: true };
  }
  if (item.state === "retrying") {
    return { label: "transactions.recurring.next.debit", at: item.next_attempt_at, withTime: true };
  }
  return { label: "transactions.recurring.next.expiry", at: item.expire_at, withTime: false };
}
