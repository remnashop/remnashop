import type { ParseKeys } from "i18next";
import { CalendarDays, CreditCard, FileText, Hash, Repeat, RotateCcw, SearchCheck, ShieldCheck, Smartphone, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getRecurringConsent,
  runRecurringAction,
  type RecurringAction,
  type RecurringPaymentItem,
} from "@entities/transactions/recurring-api";
import { usePermissions } from "@entities/user/use-current-user";
import { getErrorMessage } from "@shared/api/http";
import { formatDuration } from "@shared/lib/duration";
import { useOpenEntity } from "@shared/lib/entity-dialogs";
import { formatMoney } from "@shared/lib/format";
import { formatDate, formatDateTime } from "@shared/lib/relative-time";
import { toast } from "@shared/lib/toast";
import { useAsyncResource } from "@shared/lib/use-async-resource";
import { Badge } from "@shared/ui/Badge";
import { Button } from "@shared/ui/Button";
import { ConfirmDialog } from "@shared/ui/ConfirmDialog";
import { DialogCard } from "@shared/ui/glass/DialogCard";
import { DialogHeader } from "@shared/ui/glass/DialogHeader";
import { InfoRow } from "@shared/ui/InfoRow";
import { KpiTile } from "@shared/ui/KpiTile";
import { Modal } from "@shared/ui/Modal";
import { GLASS_DIALOG_BODY_CLASS, GLASS_DIALOG_FOOTER_CLASS } from "@shared/ui/classes";

import { RECURRING_STATE_TONE } from "./state-tone";

export function RecurringPaymentDialog({
  item,
  onClose,
  onChanged,
}: {
  item: RecurringPaymentItem;
  onClose: () => void;
  onChanged: () => void;
}) {
  return (
    <Modal onClose={onClose} size="lg" scrollable>
      <RecurringPaymentContent item={item} onChanged={onChanged} onClose={onClose} />
    </Modal>
  );
}

function RecurringPaymentContent({
  item,
  onChanged,
  onClose,
}: {
  item: RecurringPaymentItem;
  onChanged: () => void;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const permissions = usePermissions();
  const { openOrder, openSubscription } = useOpenEntity();
  const [running, setRunning] = useState<RecurringAction | null>(null);
  const [isConfirmingClose, setIsConfirmingClose] = useState(false);
  const canViewConsent = permissions.includes("TRANSACTIONS_RECURRING_CONSENT_VIEW");
  const [consentState] = useAsyncResource((signal) =>
    canViewConsent ? getRecurringConsent(item.subscription_id, signal) : Promise.resolve(null),
  );
  const consent = consentState.kind === "ready" ? consentState.data : null;
  const none = t("common.none");
  const date = (value: string | null) => (value ? formatDateTime(value, i18n.language) : none);
  const expired = new Date(item.expire_at).getTime() < Date.now();
  const reason = item.last_error;
  const hint = reason ? t(`transactions.recurring.hints.${reason}` as ParseKeys, { defaultValue: "" }) : "";

  const run = async (action: RecurringAction) => {
    setRunning(action);
    try {
      await runRecurringAction(item.subscription_id, action, item.pending_transaction_id);
      toast.success(t("transactions.recurring.actions.done"));
      onChanged();
      onClose();
    } catch (error) {
      toast.error(getErrorMessage(error, t("common.errors.generic")));
    } finally {
      setRunning(null);
    }
  };

  const canCheck = item.can_check && permissions.includes("TRANSACTIONS_RECURRING_CHECK");
  const canClose = item.can_close && permissions.includes("TRANSACTIONS_RECURRING_CLOSE");
  const canRetry = item.can_retry && permissions.includes("TRANSACTIONS_RECURRING_RETRY");

  return (
    <>
      <DialogHeader
        icon={Repeat}
        title={t("transactions.recurring.dialog.title", { id: item.subscription_id })}
        subtitle={`${item.user_name ?? none} · ${item.plan_name}`}
        actions={
          <Button variant="glass" size="sm" onClick={() => openSubscription(item.subscription_id)}>
            {t("transactions.recurring.dialog.openSubscription")}
          </Button>
        }
      />

      <div className={GLASS_DIALOG_BODY_CLASS}>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <KpiTile
              glass
              label={t("transactions.recurring.limit")}
              value={item.amount_limit && item.currency ? formatMoney(item.amount_limit, item.currency, i18n.language, true) : none}
              hint={item.duration_days ? formatDuration(item.duration_days, t) : undefined}
            />
            <KpiTile
              glass
              label={t("transactions.recurring.dialog.expiry")}
              value={formatDate(item.expire_at, i18n.language)}
              hint={expired ? t("transactions.recurring.dialog.expired") : undefined}
            />
          </div>

          <DialogCard title={t("transactions.recurring.dialog.sections.state")} icon={ShieldCheck}>
            <div className="flex flex-col gap-2 px-2 py-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={RECURRING_STATE_TONE[item.state]}>{t(`transactions.recurring.states.${item.state}`)}</Badge>
                {reason && <span className="font-mono text-xs text-muted-foreground">{reason}</span>}
              </div>
              {reason && (
                <p className="text-sm leading-relaxed text-foreground/80">
                  {t(`transactions.recurring.reasons.${reason}` as ParseKeys, { defaultValue: reason })}
                  {hint && <>. {hint}</>}
                </p>
              )}
              {item.first_failure_at && (
                <p className="text-xs text-muted-foreground">
                  {t("transactions.recurring.dialog.firstFailure", {
                    date: formatDateTime(item.first_failure_at, i18n.language),
                    count: item.retry_count,
                  })}
                </p>
              )}
            </div>
          </DialogCard>

          <DialogCard title={t("transactions.recurring.dialog.sections.payment")} icon={CreditCard}>
            <InfoRow
              icon={Hash}
              label={t("transactions.recurring.dialog.order")}
              mono
              action={
                item.pending_transaction_id !== null && permissions.includes("TRANSACTIONS_DETAIL_VIEW") ? (
                  <Button variant="glass" size="sm" onClick={() => openOrder(item.pending_transaction_id!)}>
                    {t("transactions.recurring.dialog.openOrder")}
                  </Button>
                ) : undefined
              }
            >
              {item.pending_transaction_id !== null ? `#${item.pending_transaction_id}` : none}
            </InfoRow>
            <InfoRow icon={Hash} label={t("transactions.recurring.dialog.providerId")} copyValue={item.external_payment_id ?? undefined} mono>
              {item.external_payment_id ?? none}
            </InfoRow>
            <InfoRow icon={CalendarDays} label={t("transactions.recurring.dialog.submitted")} mono>
              {date(item.submitted_at)}
            </InfoRow>
            <InfoRow icon={CalendarDays} label={t("transactions.recurring.dialog.nextAttempt")} mono>
              {date(item.next_attempt_at)}
            </InfoRow>
            <InfoRow icon={CreditCard} label={t("transactions.recurring.dialog.savedCard")}>
              {item.has_saved_method ? t("common.yes") : t("common.no")}
            </InfoRow>
          </DialogCard>

          {consent && (
            <DialogCard title={t("transactions.recurring.dialog.sections.consent")} icon={FileText}>
              <InfoRow icon={CalendarDays} label={t("transactions.recurring.dialog.acceptedAt")} mono>
                {formatDateTime(consent.accepted_at, i18n.language)}
              </InfoRow>
              <InfoRow icon={Smartphone} label={t("transactions.details.channel")}>
                {t(`transactions.channel.${consent.channel}`)}
              </InfoRow>
              {consent.revoked_at && (
                <InfoRow icon={XCircle} label={t("transactions.recurring.dialog.revokedAt")} mono>
                  {formatDateTime(consent.revoked_at, i18n.language)}
                </InfoRow>
              )}
            </DialogCard>
          )}
          {consent && (
            <DialogCard title={t("transactions.recurring.dialog.termsText")} icon={FileText} collapsible>
              <p className="whitespace-pre-line px-2 py-1.5 text-sm leading-relaxed text-foreground/80">
                {consent.terms.text}
              </p>
            </DialogCard>
          )}
        </div>
      </div>

      {(canCheck || canClose || canRetry) && (
        <div className={GLASS_DIALOG_FOOTER_CLASS}>
          {canClose && (
            <Button variant="glassDanger" onClick={() => setIsConfirmingClose(true)} isLoading={running === "close"}>
              <XCircle className="size-4" />
              {t("transactions.recurring.actions.close")}
            </Button>
          )}
          <span className="flex-1" />
          {canCheck && (
            <Button variant="glass" onClick={() => void run("check")} isLoading={running === "check"}>
              <SearchCheck className="size-4" />
              {t("transactions.recurring.actions.check")}
            </Button>
          )}
          {canRetry && (
            <Button variant="glassAccent" onClick={() => void run("retry")} isLoading={running === "retry"}>
              <RotateCcw className="size-4" />
              {t("transactions.recurring.actions.retry")}
            </Button>
          )}
        </div>
      )}

      {isConfirmingClose && (
        <ConfirmDialog
          title={t("transactions.recurring.actions.closeTitle")}
          message={t("transactions.recurring.actions.closeMessage")}
          confirmLabel={t("transactions.recurring.actions.close")}
          cancelLabel={t("common.cancel")}
          danger
          onCancel={() => setIsConfirmingClose(false)}
          onConfirm={() => {
            setIsConfirmingClose(false);
            void run("close");
          }}
        />
      )}
    </>
  );
}
