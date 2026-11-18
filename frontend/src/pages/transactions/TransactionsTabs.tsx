import { Receipt, Repeat } from "lucide-react";
import { useTranslation } from "react-i18next";

import { usePermissions } from "@entities/user/use-current-user";
import { TabBar } from "@shared/ui/glass/TabBar";

type TransactionsTab = "orders" | "recurring";

const TABS = [
  { key: "orders", to: "/dashboard/transactions", icon: Receipt },
  { key: "recurring", to: "/dashboard/transactions/recurring", icon: Repeat },
] as const;

/** Orders | auto-renewals: shown only to someone who may open both. */
export function TransactionsTabs({ active }: { active: TransactionsTab }) {
  const { t } = useTranslation();
  const permissions = usePermissions();
  if (!permissions.includes("TRANSACTIONS_VIEW") || !permissions.includes("TRANSACTIONS_RECURRING_VIEW")) {
    return null;
  }
  return (
    <div className="min-w-0 shrink-0">
      <TabBar
        items={TABS.map((tab) => ({ ...tab, label: t(`transactions.tabs.${tab.key}`), isActive: tab.key === active }))}
      />
    </div>
  );
}
