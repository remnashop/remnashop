ntf-test = Push-уведомления на этом устройстве работают.
    .title = Тестовое уведомление
ntf-session-theft-detected = Повторное использование refresh-токена завершило сессию #{ $session_id } пользователя #{ $user_id }. IP: { $ip }
    .title = Обнаружена кража сессии!
    .emoji = ⚠️
ntf-login-failed = Неверный пароль для «{ $login }». IP: { $ip }
    .title = Неудачный вход в панель управления!
    .emoji = ⚠️
ntf-passkey-login-failed = Вход по Passkey отклонён. IP: { $ip }
    .title = Неудачный вход в панель управления!
    .emoji = ⚠️
ntf-oauth-login-failed = Вход через { $provider ->
        [GITHUB] GitHub
        [TELEGRAM] Telegram
        [GOOGLE] Google
        [YANDEX] Яндекс
       *[OIDC] OIDC
    } отклонён. IP: { $ip }
    .title = Неудачный вход в панель управления!
    .emoji = ⚠️
ntf-backup-failed = Резервная копия { $kind ->
        [ASSETS] файлов
       *[DATABASE] базы данных
    } не создана: { $error }
    .title = Ошибка резервного копирования!
    .emoji = ⚠️
ntf-bonus-days-renewal-stuck = Бонус-дни ({ $days }) пользователя #{ $user_id } не применены к подписке #{ $subscription_id }: { $error }. Примените вручную.
    .title = Бонусные дни не применены!
    .emoji = ⚠️
ntf-subscription-purchased = Клиент: { $user }
    .title = { $is_trial ->
        [yes] Пробная подписка активирована!
       *[no] { $purchase_type ->
            [CHANGE] План подписки изменён!
            [RENEW] Подписка продлена!
           *[other] Подписка куплена!
        }
    }
ntf-subscription-renewed = Клиент: { $user }, { $duration_days ->
        [0] бессрочно
       *[other] на { $duration_days ->
            [one] { $duration_days } день
            [few] { $duration_days } дня
           *[other] { $duration_days } дней
        }
    }
    .title = Подписка продлена!
ntf-transaction-refunded = Заказ #{ $order_id }: возврат { $money } через { $gateway_type }
    .title = Транзакция возвращена!
    .emoji = ⚠️
ntf-transaction-partially-refunded = Заказ #{ $order_id }: частичный возврат { $money } через { $gateway_type }, проверьте вручную
    .title = Транзакция возвращена частично!
    .emoji = ⚠️
ntf-transaction-fulfilled-manually = Заказ #{ $order_id }, клиент { $target }, выдал { $actor }
    .title = Заказ выдан вручную!
ntf-paid-order-not-fulfilled = Заказ #{ $order_id }: { $money } через { $gateway_type } оплачен, но подписка ещё не выдана. Проверьте заказ.
    .title = Оплаченный заказ не выдан!
    .emoji = ⚠️
ntf-broadcast-completed = Рассылка #{ $broadcast_id } завершена: доставлено { $sent }, ошибок { $failed }, заблокировали бота { $blocked }.
    .title = Рассылка завершена!
ntf-daily-report = Новых пользователей: { $new_users }, новых платящих: { $new_payers }, выручка { $revenue_money }.
    .title = Отчёт за { $day }
    .emoji = 📊
ntf-broadcast-failed = Рассылка #{ $broadcast_id } остановлена: { $error }
    .title = Ошибка рассылки!
    .emoji = ⚠️
ntf-suppressed = Не отправлено похожих уведомлений с прошлого раза: { $count }.
ntf-sources-merged = Уведомления из нескольких источников объединены; показан последний источник.
ntf-customer-open-cabinet = Открыть кабинет
email-login-code = Код действует 10 минут.
    .title = Код для входа: { $code }
email-link-code = Введите его в кабинете, чтобы добавить эту почту к аккаунту. Код действует 10 минут.
    .title = Код для привязки почты: { $code }
btn-customer-notification =
    .renew = Продлить подписку
    .renew-icon = 🔄
    .buy = Купить подписку
    .buy-icon = 💳
    .menu = К покупке
    .menu-icon = 💳
    .close = Закрыть
    .close-icon = ❌
    .connect = Подключиться
    .connect-icon = 🚀
    .support = Перейти в поддержку
    .support-icon = 📩
    .revoke-sessions = Завершить все сессии
    .revoke-sessions-icon = 🔒
ntf-customer-sessions-revoked = ✅ Мы завершили все сеансы в личном кабинете. Если это были не вы, напишите в поддержку — разберёмся вместе.
ntf-customer-subscription-purchased = Чтобы начать пользоваться сервисом, подключите устройство и следуйте инструкциям — это займёт пару минут.
    .title = { $is_trial ->
        [yes] Пробная подписка активирована
       *[no] { $paid ->
            [yes] Оплата прошла успешно!
           *[no] Подписка активирована
        }
    }
    .emoji = { $is_trial ->
        [yes] 🎁
       *[no] ✅
    }
ntf-customer-subscription-renewed = { $duration_days ->
        [0] Ваша подписка теперь бессрочная.
       *[other] Ваша подписка продлена на { $duration_days ->
            [one] { $duration_days } день
            [few] { $duration_days } дня
           *[other] { $duration_days } дней
        }.
    }
    .title = { $paid ->
        [yes] Оплата прошла успешно!
       *[no] Подписка продлена
    }
    .emoji = ✅
ntf-customer-subscription-changed = { $has_plan_name ->
        [yes] Ваша подписка переведена на тариф «{ $plan_name }».
       *[other] Ваша подписка изменена.
    } Подключение остаётся прежним, ничего настраивать не нужно.
    .title = { $paid ->
        [yes] Оплата прошла успешно!
       *[no] Тариф изменён
    }
    .emoji = ✅
ntf-customer-subscription-add-on-granted = { $addon_type ->
        [TRAFFIC] К подписке добавлено { $amount } ГБ трафика.
       *[DEVICES] К подписке добавлено { $amount ->
            [one] { $amount } устройство
            [few] { $amount } устройства
           *[other] { $amount } устройств
        }.
    }
    .title = Дополнение активировано
    .emoji = 🎁
ntf-customer-subscription-granted = { $has_plan_name ->
        [yes] Подписка «{ $plan_name }»
       *[other] Подписка
    } { $duration_days ->
        [0] навсегда.
       *[other] на { $duration_days ->
            [one] { $duration_days } день
            [few] { $duration_days } дня
           *[other] { $duration_days } дней
        }.
    } Подключите устройство, чтобы начать пользоваться.
    .title = Вам выдана подписка
    .emoji = 🎁
ntf-customer-transaction-refunded = { $money } вернутся тем же способом, которым вы платили.
    .title = Платёж возвращён
    .emoji = 💸
ntf-customer-transaction-partially-refunded = Часть платежа, { $money }, вернётся тем же способом, которым вы платили.
    .title = Частичный возврат
    .emoji = 💸
ntf-customer-paid-order-not-fulfilled = Оплата { $money } получена, но подписка выдаётся дольше обычного. Мы уже разбираемся: выдадим подписку или вернём деньги. Если вопрос не решится в ближайшее время, напишите в поддержку.
    .title = Выдача задерживается
    .emoji = ⏳
ntf-customer-subscription-expiring = { $is_trial ->
        [yes] Ваш пробный период закончится через { $span_unit ->
        [day] { $span ->
            [one] { $span } день
            [few] { $span } дня
           *[other] { $span } дней
        }
       *[hour] { $span } ч
    }. Оформите подписку, чтобы не терять доступ к сервису.
       *[no] Ваша подписка закончится через { $span_unit ->
        [day] { $span ->
            [one] { $span } день
            [few] { $span } дня
           *[other] { $span } дней
        }
       *[hour] { $span } ч
    }. Продлите её заранее, чтобы не терять доступ к сервису.
    }
    .title = { $is_trial ->
        [yes] Пробный период скоро закончится
       *[no] Подписка скоро закончится
    }
    .emoji = ⚠️
ntf-customer-subscription-expired = { $is_trial ->
        [yes] Ваш пробный период закончился. Оформите подписку, чтобы продолжить пользоваться VPN.
       *[no] Ваша подписка истекла. Продлите её, чтобы продолжить пользоваться VPN.
    }
    .title = { $is_trial ->
        [yes] Пробный период закончился — VPN не работает
       *[no] Подписка истекла — VPN не работает
    }
    .emoji = ⛔
ntf-customer-subscription-grace-started = Ваша подписка истекла. { $grace_until ->
        [none] Действует
       *[other] До { $grace_until } действует
    } льготный доступ{ $traffic_unit ->
        [gb]: { $traffic_value } ГБ
        [mb]: { $traffic_value } МБ
       *[none] {""}
    }. Продлите подписку, чтобы вернуть тариф.
    .title = Подписка истекла
    .emoji = ⏳
ntf-customer-subscription-expiry-disable-warning = { $is_trial ->
        [yes] Ваш пробный период закончился, и { $disable_date } доступ будет отключён полностью. Оформите подписку, чтобы продолжить пользоваться VPN.
       *[no] Ваша подписка истекла, и { $disable_date } доступ будет отключён полностью. Продлите подписку, чтобы продолжить пользоваться VPN.
    }
    .title = Доступ скоро отключится
    .emoji = ⚠️
ntf-customer-subscription-traffic-limited = Ваш трафик израсходован. { $is_trial ->
        [yes] Оформите подписку, чтобы продолжить пользоваться сервисом.
       *[no] { $traffic_strategy ->
            [DAY] Он восстановится завтра, или продлите подписку, чтобы сбросить его сейчас.
            [WEEK] Он восстановится в начале следующей недели, или продлите подписку, чтобы сбросить его сейчас.
            [MONTH] Он восстановится в начале следующего месяца, или продлите подписку, чтобы сбросить его сейчас.
            [MONTH_ROLLING] Он восстановится в день ежемесячного сброса, или продлите подписку, чтобы сбросить его сейчас.
           *[NO_RESET] Продлите подписку, чтобы сбросить трафик и продолжить пользоваться сервисом.
        }
    }
    .title = Трафик закончился — VPN не работает
    .emoji = ⛔
ntf-customer-subscription-traffic-threshold = { $percent ->
        [0] Трафик подходит к концу.
       *[other] Израсходовано { $percent }% трафика.
    }{ $reset_date ->
        [none] {""}
       *[other] {" "}Он восстановится { $reset_date }.
    }{ $is_trial ->
        [yes] {" "}Оформите подписку, чтобы не потерять доступ.
       *[no] { $can_renew ->
            [yes] {" "}Продлите подписку, чтобы восстановить его сейчас.
           *[no] {""}
        }
    }
    .title = Трафик на исходе
    .emoji = ⚠️
ntf-customer-cabinet-new-device-sign-in = Кто-то вошёл в ваш личный кабинет с IP-адресом { $ip } ({ $browser }). Если это были не вы — завершите сессии на всех устройствах и напишите в поддержку.
    .title = Вход с нового устройства
    .emoji = 🔐
ntf-customer-accounts-merged = Подписки, платежи и способы входа другого аккаунта теперь здесь. Если это были не вы — напишите в поддержку.
    .title = Аккаунты объединены
    .emoji = 🔗
ntf-customer-referral-reward-issued = Приглашённый совершил платёж — вам начислено { $amount } { $reward_type ->
        [EXTRA_DAYS] { $amount ->
            [one] бонусный день
            [few] бонусных дня
           *[other] бонусных дней
        }
        [POINTS] { $amount ->
            [one] балл
            [few] балла
           *[other] баллов
        }
       *[other] вознаграждение
    }. Спасибо, что пригласили!
    .title = Вам начислена награда!
    .emoji = 💰
ntf-customer-invitee-reward-issued = Вам начислено { $amount } { $reward_type ->
        [EXTRA_DAYS] { $amount ->
            [one] бонусный день
            [few] бонусных дня
           *[other] бонусных дней
        }
        [POINTS] { $amount ->
            [one] балл
            [few] балла
           *[other] баллов
        }
       *[other] вознаграждение
    } за регистрацию по приглашению.
    .title = Приветственный бонус
    .emoji = 🎁
ntf-panel-login-failed = Неудачный вход в панель Remnawave под «{ $username }». IP: { $ip }
    .title = Неудачный вход в панель Remnawave!
    .emoji = ⚠️
ntf-panel-login-succeeded = Вход в панель Remnawave под «{ $username }». IP: { $ip }
    .title = Вход в панель Remnawave!
ntf-rescue-cli-used = { $action ->
        [reset_owner_access] Сброшен доступ владельца: новый пароль, очищен IP-allowlist, удалены сессии, passkey и привязки.
        [enable_password_login] Включён вход по паролю.
        [reset_encrypted_secrets] Стёрты все секреты из базы: заново введите токен бота, ключи шлюзов, OAuth, SMTP и капчи.
       *[restore_backup] База восстановлена из резервной копии.
    }
    .title = Использована консоль восстановления!
    .emoji = ⚠️
ntf-required-channel-check-failed = Бот не может проверить подписку на канал { $channel_id }: { $error }. Пока проблема не решена, клиенты проходят без проверки.
    .title = Ошибка проверки обязательного канала!
    .emoji = ⚠️
    .hint = Пока проблема не решена, клиенты проходят без проверки.
ntf-telegram-webhook-failed = Ошибка вебхука Telegram: { $error }
    .title = Ошибка вебхука Telegram!
    .emoji = ⚠️
ntf-node-connection-lost = Соединение с узлом «{ $node_name }» потеряно.
    .title = Соединение с узлом потеряно!
    .emoji = ⚠️
ntf-node-connection-restored = Соединение с узлом «{ $node_name }» восстановлено.
    .title = Соединение с узлом восстановлено!
ntf-node-traffic-reached = Узел «{ $node_name }» достиг лимита трафика.
    .title = Узел достиг лимита трафика!
    .emoji = ⚠️
ntf-node-billing-due = Оплата узла «{ $node_name }» у { $provider } — { $next_billing_at }.
    .title = Подходит срок оплаты узла!
ntf-remnawave-unavailable = Соединение с Remnawave потеряно ({ $error }).
    .title = Соединение с Remnawave потеряно!
    .emoji = ⚠️
ntf-remnawave-restored = Соединение с Remnawave восстановлено.
    .title = Соединение с Remnawave восстановлено!
ntf-outbox-entry-poisoned = Событие { $failed_event } (#{ $outbox_id }) не обработано за { $attempts } попыток: { $error }
    .title = Событие не обработано!
    .emoji = ⚠️
ntf-system-health-degraded = { $kind ->
        [process_down] Процесс { $subject } не отвечает.
        [host_disk_full] Диск сервера заполнен на { $value }%.
        [host_memory_high] Память сервера занята на { $value }%.
        [outbox_stuck] Очередь событий не обрабатывается: дольше 5 минут ждут { $value }.
        [gateway_failures] Платежи через { $subject } не проходят: ошибок за час — { $value }.
        [smtp_failed] Почта не отправляется: { $subject ->
            [bulk] SMTP для рассылок
           *[main] основной SMTP
        } отвечает ошибкой.
       *[event_loop_lag] Процесс { $subject } работает с задержкой: p99 event loop — { $value } мс.
    }
    .title = Критическое состояние системы!
    .emoji = ⚠️
ntf-system-health-restored = { $kind ->
        [process_down] Процесс { $subject } снова работает.
        [host_disk_full] Заполненность диска сервера вернулась к норме.
        [host_memory_high] Использование памяти сервера вернулось к норме.
        [outbox_stuck] Очередь событий снова обрабатывается.
        [gateway_failures] Платежи через { $subject } снова проходят.
        [smtp_failed] Почта снова отправляется: { $subject ->
            [bulk] SMTP для рассылок
           *[main] основной SMTP
        } работает.
       *[event_loop_lag] Задержка процесса { $subject } вернулась к норме.
    }
    .title = Состояние системы восстановлено!
ntf-remnawave-version-mismatch = Remnawave { $version } вне поддерживаемого диапазона { $supported }.
    .title = Неподдерживаемая версия Remnawave!
    .emoji = ⚠️
ntf-panel-started = Панель Remnawave перезапущена.
    .title = Панель Remnawave запущена!
ntf-bot-started = Бот @{ $username } запущен.
    .title = Бот запущен!
ntf-bot-stopped = Бот остановлен.
    .title = Бот остановлен!
ntf-telegram-user-registered = Новый клиент { $user } пришёл через бота.
    .title = Регистрация в боте!
ntf-cabinet-user-registered = Новый клиент { $user } пришёл через веб-кабинет, вход через { $method ->
        [EMAIL] почту
        [GOOGLE] Google
        [YANDEX] Яндекс
       *[TELEGRAM] Telegram
    }.
    .title = Регистрация в кабинете!
ntf-telegram-registration-blocked = Регистрация { $user } через бота заблокирована.
    .title = Регистрация в боте заблокирована!
ntf-cabinet-registration-blocked = Регистрация { $user } через веб-кабинет заблокирована.
    .title = Регистрация в кабинете заблокирована!
ntf-subscription-first-connected = Клиент: { $user }
    .title = Подписка подключена впервые!
ntf-torrent-blocker-report = Торрент-трафик { $user } заблокирован на «{ $node_name }» ({ $destination }).
    .title = Торрент-трафик заблокирован!
    .emoji = ⚠️
ntf-subscription-expired = Подписка { $user } истекла.
    .title = Подписка истекла!
ntf-subscription-traffic-limited = У { $user } закончился трафик.
    .title = Лимит трафика исчерпан!
ntf-subscription-revoked = Клиент: { $user }
    .title = Ссылка подписки перевыпущена!
ntf-subscription-not-connected = Клиент { $user }, { $hours } ч после оформления
    .title = Подписка не подключена!
ntf-customer-subscription-not-connected = Вы оформили подписку { $span_unit ->
        [day] { $span ->
            [one] { $span } день
            [few] { $span } дня
           *[other] { $span } дней
        }
       *[hour] { $span } ч
    } назад, но ещё ни разу ею не воспользовались. Если с настройкой возникли сложности, напишите в поддержку — разберёмся вместе.
    .title = Не получилось подключиться?
    .emoji = 🔌
ntf-customer-subscription-expired-ago = { $is_trial ->
        [yes] Ваш пробный период закончился { $span_unit ->
        [day] { $span ->
            [one] { $span } день
            [few] { $span } дня
           *[other] { $span } дней
        }
       *[hour] { $span } ч
    } назад. Оформите подписку, чтобы снова пользоваться VPN.
       *[no] Ваша подписка истекла { $span_unit ->
        [day] { $span ->
            [one] { $span } день
            [few] { $span } дня
           *[other] { $span } дней
        }
       *[hour] { $span } ч
    } назад. Продлите её, чтобы снова пользоваться VPN.
    }
    .title = { $is_trial ->
        [yes] Пробный период закончился — VPN не работает
       *[no] Подписка истекла — VPN не работает
    }
    .emoji = ⛔
ntf-customer-torrent-blocker-report = Мы заметили торрент-трафик через VPN. Торренты запрещены правилами сервиса, поэтому подключение ограничено{ $block_unit ->
        [minute] { " " }на { $block_span ->
            [one] { $block_span } минуту
            [few] { $block_span } минуты
           *[other] { $block_span } минут
        }
        [hour] { " " }на { $block_span } ч
       *[none] {""}
    }. Отключите торрент-клиент или исключите его из VPN, чтобы это не повторялось. При повторных нарушениях доступ может быть ограничен навсегда.
    .title = Подключение временно ограничено
    .emoji = ⛔
ntf-customer-promocode-discount-expiring = { $percent }% по промокоду { $code } действуют ещё { $span_unit ->
        [day] { $span ->
            [one] { $span } день
            [few] { $span } дня
           *[other] { $span } дней
        }
        [minute] { $span } мин
       *[hour] { $span } ч
    }. Успейте оформить покупку.
    .title = Скидка скоро сгорит
    .emoji = ⏳
ntf-customer-payments-restored = Возможность оплаты восстановлена! Теперь вы можете купить или продлить подписку. Спасибо за ожидание.
    .title = Оплата снова доступна
    .emoji = ❇️
ntf-telegram-label =
    .event = Событие
    .user = Пользователь
    .id = ID
    .telegram-id = Telegram ID
    .name = Имя
    .username = Username
    .email = Почта
    .details = Детали
    .payment = Платёж
    .subscription = Подписка
    .trial-subscription = Пробная подписка
    .plan = План
    .trial-plan = Пробный план
    .promocode = Промокод
    .device = Устройство
    .build = Сборка
    .access = Доступность
    .session = Сессия
    .order = Заказ
    .ip = IP
    .login = Логин
    .method = Способ
    .provider = Провайдер
    .user-agent = User-Agent
    .kind = Тип
    .run = Запуск
    .bonus-days = Бонус-дни
    .channel = Канал
    .error = Ошибка
    .node = Узел
    .reason = Причина
    .billing-date = Дата оплаты
    .version = Версия
    .supported = Поддерживается
    .bot = Бот
    .broadcast = Рассылка
    .sent = Доставлено
    .failed = Ошибок
    .blocked = Заблокировали бота
    .admin = Администратор
    .previous-status = Прежний статус
    .ad-link = Рекламная ссылка
    .referral-code = Реферальный код
    .sign-in-method = Способ входа
    .hours = Прошло часов
    .destination = Адрес
    .payment-method = Способ оплаты
    .amount = Сумма
    .refund = Возврат
    .status = Статус
    .traffic = Трафик
    .traffic-limit = Лимит трафика
    .device-limit = Лимит устройств
    .left = Осталось
    .duration = Длительность
    .type = Тип
    .code = Код
    .reward = Награда
    .branch = Ветка
    .commit = Коммит
    .build-time = Время сборки
    .mode = Режим
    .payments = Платежи
    .registration = Регистрация
    .uptime = Аптайм
    .hwid = HWID
    .platform = Платформа
    .model = Модель
    .os-version = Версия ОС
    .channel-bot = Бот
    .channel-cabinet = Веб-кабинет
    .method-password = Пароль
    .method-passkey = Passkey
    .method-oauth = OAuth
    .refund-full = полный
    .refund-partial = частичный
    .unlimited = Безлимит
    .report-day = За сутки
    .new-users = Новых пользователей
    .new-trials = Новых пробных
    .trial-conversions = Пробная → платная
    .new-payers = Новых платящих
    .revenue = Выручка
    .report-subscriptions = Подписки сейчас
    .active-trials = Активных пробных
    .active-paid = Активных платных
    .paid-never-connected = Платных без подключения
    .report-payments = Оплаты
    .purchases = Покупки
    .renewals = Продления
    .changes = Смены тарифа
    .report-referrers = Топ по приглашениям
    .unnamed-user = Пользователь
ntf-telegram-subscription-status = { $value ->
        [ACTIVE] Активна
        [LIMITED] Исчерпан трафик
        [EXPIRED] Истекла
        [DISABLED] Отключена
        [DELETED] Удалена
       *[other] { $value }
    }
ntf-telegram-plan-type = { $value ->
        [TRAFFIC] Трафик
        [DEVICES] Устройства
        [BOTH] Трафик + устройства
       *[UNLIMITED] Безлимитный
    }
ntf-telegram-transaction-status = { $value ->
        [PENDING] Ожидает оплаты
        [PAID] Оплачен
        [FAILED] Ошибка выдачи
        [CANCELED] Отменён
        [REFUNDED] Возвращён
       *[other] { $value }
    }
ntf-telegram-backup-kind = { $value ->
        [DATABASE] База данных
        [ASSETS] Файлы
       *[other] { $value }
    }
ntf-telegram-sign-in-method = { $value ->
        [TELEGRAM] Telegram
        [EMAIL] Почта
        [GOOGLE] Google
        [YANDEX] Яндекс
       *[other] { $value }
    }
ntf-telegram-oauth-provider = { $value ->
        [GITHUB] GitHub
        [TELEGRAM] Telegram
        [OIDC] OIDC
        [GOOGLE] Google
        [YANDEX] Яндекс
       *[other] { $value }
    }
ntf-telegram-access-mode = { $value ->
        [PUBLIC] разрешён для всех
        [INVITED] разрешён для приглашённых
        [RESTRICTED] запрещён для всех
       *[other] { $value }
    }
ntf-telegram-payments = { $value ->
        [yes] разрешены
       *[no] запрещены
    }
ntf-telegram-registration = { $value ->
        [yes] разрешена
       *[no] запрещена
    }
ntf-telegram-promocode-type = { $value ->
        [DURATION] Длительность
        [TRAFFIC] Трафик
        [DEVICES] Устройства
        [SUBSCRIPTION] Подписка
        [PERSONAL_DISCOUNT] Персональная скидка
        [PURCHASE_DISCOUNT] Скидка на покупку
       *[other] { $value }
    }
ntf-telegram-unlimited = бессрочно
ntf-telegram-days = { $count ->
        [one] { $count } день
        [few] { $count } дня
       *[other] { $count } дней
    }
ntf-telegram-uptime = { $days ->
        [0] { $hours } ч { $minutes } мин
       *[other] { $days } д { $hours } ч
    }
ntf-telegram-traffic = { $unit ->
        [MB] { $amount } МБ
        [TB] { $amount } ТБ
       *[GB] { $amount } ГБ
    }
ntf-subscription-changed = Клиент: { $user }
    .title = План подписки изменён!
ntf-subscription-device-added = Клиент: { $user }
    .title = Устройство добавлено!
ntf-subscription-device-removed = Клиент: { $user }
    .title = Устройство удалено!
ntf-promocode-activated = Клиент: { $user }
    .title = Промокод активирован!
ntf-customer-referral-attached = Пользователь присоединился по вашей пригласительной ссылке.{ $rewarded ->
        [yes] { " " }Награду вы получите после первой оплаты приглашённого.
       *[no] {""}
    }
    .title = Вы пригласили друга!
    .emoji = 🎉

ntf-recurring-reason = { $reason ->
    [admin_closed] ожидание платежа закрыто администратором
    [customer_disabled] клиент отключил автопродление
    [bank_declined] банк отклонил платёж
    [insufficient_funds] недостаточно средств
    [issuer_unavailable] банк временно недоступен
    [payment_method_unavailable] способ оплаты временно недоступен
    [provider_unavailable] нет связи с платёжным сервисом
    [merchant_unavailable] магазину недоступно проведение платежей
    [provider_configuration_error] требуется исправить настройки платежа или чека
    [provider_request_rejected] ЮKassa не приняла платёж с сохранённой карты: карту отклонили или в настройках магазина ошибка
    [provider_rejected] платёжный сервис отклонил запрос
    [permission_revoked] разрешение на списания отозвано в платёжном сервисе
    [payment_method_restricted] сохранённый способ оплаты больше не действует
    [card_expired] истёк срок действия карты
    [fraud_suspected] платёж заблокирован банком
    [price_changed] цена превышает согласованный предел
    [subscription_changed] изменились условия подписки
    [shop_changed] изменился магазин для приёма платежей
    [consent_required] требуется подтверждение условий автопродления
    [plan_unavailable] тариф недоступен для покупки
    [customer_email_required] для чека требуется адрес электронной почты
    [gateway_disabled] приём автоплатежей выключен магазином
    [subscription_unavailable] подписка недоступна для продления
    [payment_status_unknown] результат предыдущего платежа пока неизвестен
    [pending_timeout] платёж слишком долго ожидает подтверждения
    [retries_exhausted] закончились повторные попытки оплаты
    [payment_method_not_saved] платёжный сервис не сохранил способ оплаты
    [renewal_window_expired] истёк согласованный срок повторных списаний
    [refunded] платёж по подписке был возвращён
   *[other] возникла проблема с автоматической оплатой
    }
ntf-recurring-payment-upcoming = Подписка #{ $subscription_id }: запланировано списание до { $amount } { $currency } в { $scheduled_at }.
    .title = Предстоящий автоплатёж
ntf-recurring-payment-failed = Подписка #{ $subscription_id }, заказ #{ $order_id }: неудачная попытка #{ $attempt }, { $reason_text }.
    .title = Неудачный автоплатёж
ntf-recurring-payment-paused = Подписка #{ $subscription_id }: автоплатежи приостановлены — { $reason_text }.
    .title = Автопродление требует внимания
ntf-recurring-payment-exhausted = Подписка #{ $subscription_id }: автоматическое продление остановлено — { $reason_text }. Требуется ручная оплата.
    .title = Автоплатёж не выполнен
ntf-customer-recurring-payment-upcoming = Для подписки #{ $subscription_id } запланировано автоматическое списание до { $money } в { $scheduled_at }. Проверьте баланс. Отменить будущие списания можно в настройках этой подписки в боте.
    .title = Скоро автоматическое продление
ntf-customer-recurring-payment-failed = Не удалось автоматически оплатить подписку: { $reason_text }. { $has_next_attempt ->
    [yes] Следующая попытка: { $next_attempt_at }.
   *[no] Новая попытка пока не назначена.
    } Проверьте баланс или продлите подписку вручную.
    .title = Автоплатёж не прошёл
ntf-customer-recurring-payment-paused = Автоматическое продление подписки приостановлено: { $reason_text }. { $has_next_attempt ->
    [yes] Повторная проверка: { $next_attempt_at }.
   *[no] Проверьте настройки подписки или обратитесь в поддержку.
    } Оплаченный срок сохраняется.
    .title = Проверьте автопродление
ntf-customer-recurring-payment-exhausted = Автоматическое продление остановлено: { $reason_text }. Чтобы сохранить доступ, оплатите продление вручную.
    .title = Требуется продлить подписку
# the payment page and the fiscal receipt name the order with this
payment-description = Подписка «{ $plan }», { $period }
payment-period = { $unit ->
    [unlimited] навсегда
    [year] { $value ->
        [one] { $value } год
        [few] { $value } года
       *[other] { $value } лет
    }
    [month] { $value ->
        [one] { $value } месяц
        [few] { $value } месяца
       *[other] { $value } месяцев
    }
   *[day] { $value ->
        [one] { $value } день
        [few] { $value } дня
       *[other] { $value } дней
    }
}
# auto-renewal terms the customer accepts; the accepted text is stored with the consent
recurring-terms-summary = По вашему согласию — сохранение способа оплаты в ЮKassa и автоматические списания до { $amount } { $currency_symbol } за каждые { $days } дн., начиная за { $lead_minutes } мин. до окончания подписки. Отключить будущие списания можно в настройках подписки в боте или в личном кабинете.
recurring-terms-text =
    Условия автоматического продления

    Текущая оплата: { $initial } { $currency_symbol }.
    Продление: не более { $amount } { $currency_symbol } за каждые { $days } дн. Разовая скидка на будущие продления не распространяется. Если стоимость превысит указанный предел или изменятся условия тарифа, автосписания остановятся.

    Попытка оплаты начинается за { $lead_minutes } мин. до окончания оплаченного периода. После отказа банка возможны повторные списания через { $retry_hours } ч. от первого отказа, в пределах указанного окна. При временном сбое запрос может повторяться с интервалом { $retry_minutes } мин., но новые попытки не начинаются позднее { $overdue_hours } ч. после окончания подписки. Уже отправленный платёж может завершиться позже.

    Давая согласие, вы разрешаете сохранить способ оплаты через ЮKassa и использовать его для автоматической оплаты этой подписки без отдельного подтверждения каждого списания.

    Отозвать согласие и запретить дальнейшие списания можно кнопкой «Отключить автопродление» в настройках подписки в боте или в личном кабинете. Отказ прекращает новые попытки списания; уже отправленный платёж может завершиться. Оплаченный срок сохраняется. Сохранённый способ оплаты удаляется через { $retention_days } дн. после отказа. Повторное подключение требует нового явного согласия.
