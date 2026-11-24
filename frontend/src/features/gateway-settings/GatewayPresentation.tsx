import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ParseKeys } from "i18next";

import { updateGatewayPresentation } from "@entities/gateways/api";
import type { Gateway, GatewayText } from "@entities/gateways/api";
import { usePermissions } from "@entities/user/use-current-user";
import { getErrorMessage } from "@shared/api/http";
import { toast } from "@shared/lib/toast";
import { Button } from "@shared/ui/Button";
import { Field } from "@shared/ui/glass/Field";
import { Input } from "@shared/ui/glass/Input";

export function GatewayPresentation({ gateway, onChanged }: {
  gateway: Gateway; onChanged: (gateway: Gateway) => void;
}) {
  const { t } = useTranslation();
  const canUpdate = usePermissions().includes("GATEWAYS_UPDATE");
  const [draft, setDraft] = useState<Record<string, GatewayText> | null>(null);
  const [saving, setSaving] = useState(false);
  const texts = draft ?? gateway.presentation ?? {};
  const change = (locale: string, field: keyof GatewayText, value: string) =>
    setDraft({ ...texts, [locale]: { ...(texts[locale] ?? { name: "", description: "" }), [field]: value } });
  const save = async () => {
    setSaving(true);
    try {
      onChanged(await updateGatewayPresentation(gateway.type, texts));
      setDraft(null);
      toast.success(t("common.saved"));
    } catch (error) {
      toast.error(getErrorMessage(error, t("common.errors.generic")));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col gap-3 border-t border-white/[0.08] pt-3">
      <p className="text-sm font-medium">{t("settings.gateways.presentation.title")}</p>
      <p className="text-xs text-muted-foreground">{t("settings.gateways.presentation.hint")}</p>
      {["ru", "en"].map((locale) => (
        <div key={locale} className="flex flex-col gap-3">
          <p className="text-xs font-semibold">{locale.toUpperCase()}</p>
          <Field label={t("settings.gateways.presentation.name")} htmlFor={`gateway-${gateway.type}-${locale}-name`}>
            <Input id={`gateway-${gateway.type}-${locale}-name`} maxLength={64}
              value={texts[locale]?.name ?? ""} disabled={!canUpdate || saving}
              onChange={(event) => change(locale, "name", event.target.value)} />
          </Field>
          <Field label={t("settings.gateways.presentation.description")} htmlFor={`gateway-${gateway.type}-${locale}-description`}>
            <Input id={`gateway-${gateway.type}-${locale}-description`} maxLength={160}
              value={texts[locale]?.description ?? ""} disabled={!canUpdate || saving}
              onChange={(event) => change(locale, "description", event.target.value)} />
          </Field>
        </div>
      ))}
      {canUpdate && (
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="glass" disabled={saving} onClick={() => setDraft({
            ...texts,
            ...Object.fromEntries(["ru", "en"].map((locale) => [locale, {
              name: t(`settings.gateways.suggestions.${gateway.type}.name` as ParseKeys, { lng: locale.toLowerCase() }),
              description: t(`settings.gateways.suggestions.${gateway.type}.description` as ParseKeys, { lng: locale.toLowerCase() }),
            }])),
          })}>{t("settings.gateways.presentation.suggest")}</Button>
          <Button type="button" variant="glass" disabled={saving} onClick={() => setDraft({})}>
            {t("settings.gateways.presentation.reset")}
          </Button>
          <Button type="button" variant="glassAccent" disabled={draft === null || saving} onClick={() => void save()}>
            {t("common.save")}
          </Button>
        </div>
      )}
    </div>
  );
}
