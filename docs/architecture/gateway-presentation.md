# Gateway checkout wording review

Reviewed 2026-11-24 against current adapters and official documentation.
Suggestions are opt-in, editable RU/EN drafts, never activated automatically.
A processor supporting a method does not mean the merchant has enabled it.
No country, card brand, fees, settlement time, asset or network availability is promised.

| Gateway | Evidence / integration constraint | Source |
| --- | --- | --- |
| TELEGRAM_STARS | Telegram Stars invoice, not a card/acquiring page. | https://core.telegram.org/bots/payments-stars |
| YOOKASSA | Official methods list includes cards and SBP; hosted checkout decides merchant availability. | https://yookassa.ru/developers |
| YOOMONEY | Adapter fixes paymentType=AC: card payment, not an unconditional wallet promise. | https://yoomoney.ru/docs/wallet |
| CRYPTOMUS | Cryptocurrency invoice adapter; asset/network choices depend on provider and merchant. | https://doc.cryptomus.com |
| HELEKET | Cryptocurrency invoice adapter; asset/network choices depend on provider and merchant. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://doc.heleket.com |
| CRYPTOPAY | Cryptocurrency invoice adapter; asset/network choices depend on provider and merchant. | https://help.cr.bot/ru/articles/10279948-crypto-pay-api |
| FREEKASSA | payment_system_id is merchant-configured; do not claim every FreeKassa method is offered. | https://docs.freekassa.net |
| ROBOKASSA | Official provider documentation covers cards and SBP; merchant configuration determines available checkout methods. | https://robokassa.com/payments/payment-method/ |
| CLOUDPAYMENTS | Official documentation covers cards and SBP; available checkout options depend on merchant activation. | https://developers.cloudpayments.ru |
| LAVA | Hosted payment page; deliberately neutral wording until the merchant verifies enabled methods. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://dev.lava.ru |
| MULENPAY | Official documentation covers cards and SBP; available checkout options depend on merchant activation. | https://docs.mulenpay.com/ |
| VALUTIX | service_id can pin the merchant service; universal method claims would be unsafe. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://docs.panel.valutix.kz |
| PAYMASTER | Official provider documentation covers cards and SBP; merchant configuration determines available checkout methods. | https://paymaster.ru/docs/ru/api/ |
| PLATEGA | payment_method can pin one method; blank delegates choice to provider. | https://docs.platega.io |
| URLPAY | Official documentation covers cards and SBP; available checkout options depend on merchant activation. | https://urlpay.io/docs/api |
| WATA | Official provider documentation covers cards and SBP; merchant configuration determines available checkout methods. | https://wata.pro/api |
| ROLLYPAY | Official docs describe ruble payments including SBP; merchant settlement to USDT is not customer crypto checkout. | https://docs.rollypay.io/ |
| ANTILOPAY | Official provider documentation covers cards and SBP; merchant configuration determines available checkout methods. | https://antilopay.com/ |
| PAYPALYCH | Hosted payment page; deliberately neutral wording until the merchant verifies enabled methods. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://pally.info/reference/api |
| RIOPAY | service_id can pin the merchant service; universal method claims would be unsafe. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://docs.riopay.online/ru/docs |
| SEVERPAY | Hosted payment page; deliberately neutral wording until the merchant verifies enabled methods. | https://docs.severpay.io/en/ |
| AURAPAY | Hosted payment page; deliberately neutral wording until the merchant verifies enabled methods. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://docs.aurapay.tech/ |
| PAYPEAR | Hosted payment page; deliberately neutral wording until the merchant verifies enabled methods. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://paypear.ru/docs/ |
| CISPAY | Hosted payment page; deliberately neutral wording until the merchant verifies enabled methods. Public documentation was unavailable or JS-only during this review; no additional method claim was inferred. | https://cispay.app/developers |
| PAY_2328 | Cryptocurrency invoice adapter; asset/network choices depend on provider and merchant. | https://2328.io/api/payments |

## Compatibility and rollout

`presentation` is one atomic, non-secret localized settings bundle. PUT replaces it,
including removing locales; an empty object restores legacy names. It is independent
of encrypted provider credentials, activation, channel flags, invoice currency and routing.
Name and description accept plain single-line text (64/160 characters). The bot escapes
text through the normal window renderer; the cabinet renders React text nodes.
The customer API adds an optional map; older cabinets ignore it, newer cabinets tolerate
older servers. Missing locales fall back to English, then the legacy provider label.
Existing shops keep their names until an administrator explicitly saves text or suggestions.
Bot descriptions use method_descriptions in msg-purchase-method and method_description
in msg-purchase-confirm (including single-method checkout); customized
copies of that message need the variable added manually. Descriptions are bounded to 1800
characters in the bot, leaving space for the plan; later entries may be omitted when exceeded.
Migration 1044 adds only the empty-default presentation column. Downgrade drops those
custom labels, not payment settings. No invoice lifecycle or webhook behavior changes.
