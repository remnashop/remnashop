ntf-test = Push notifications work on this device.
    .title = Test notification
ntf-session-theft-detected = A reused refresh token ended session #{ $session_id } of user #{ $user_id }. IP: { $ip }
    .title = Session theft detected!
    .emoji = ⚠️
ntf-login-failed = Wrong password for “{ $login }”. IP: { $ip }
    .title = Dashboard sign-in failed!
    .emoji = ⚠️
ntf-passkey-login-failed = Passkey sign-in was rejected. IP: { $ip }
    .title = Dashboard sign-in failed!
    .emoji = ⚠️
ntf-oauth-login-failed = { $provider ->
        [GITHUB] GitHub
        [TELEGRAM] Telegram
        [GOOGLE] Google
        [YANDEX] Yandex
       *[OIDC] OIDC
    } sign-in was rejected. IP: { $ip }
    .title = Dashboard sign-in failed!
    .emoji = ⚠️
ntf-backup-failed = { $kind ->
        [ASSETS] Files
       *[DATABASE] Database
    } backup failed: { $error }
    .title = Backup failed!
    .emoji = ⚠️
ntf-bonus-days-renewal-stuck = { $days } bonus days of user #{ $user_id } were not applied to subscription #{ $subscription_id }: { $error }. Apply them by hand.
    .title = Bonus days not applied!
    .emoji = ⚠️
ntf-subscription-purchased = { $is_trial ->
        [yes] { $user } activated a trial
       *[no] { $user } { $purchase_type ->
            [RENEW] renewed a subscription
            [CHANGE] changed their plan
           *[NEW] bought a subscription
        }
    }
    .title = { $is_trial ->
        [yes] Trial activated!
       *[no] { $purchase_type ->
            [CHANGE] Subscription plan changed!
            [RENEW] Subscription renewed!
           *[other] Subscription purchased!
        }
    }
ntf-subscription-renewed = { $duration_days ->
        [0] { $user } renewed with no end date
       *[other] { $user } renewed for { $duration_days } days
    }
    .title = Subscription renewed!
ntf-transaction-refunded = Order #{ $order_id }: { $money } refunded via { $gateway_type }
    .title = Transaction refunded!
    .emoji = ⚠️
ntf-transaction-partially-refunded = Order #{ $order_id }: partial refund { $money } via { $gateway_type }, check it manually
    .title = Transaction partially refunded!
    .emoji = ⚠️
ntf-transaction-fulfilled-manually = { $actor } issued order #{ $order_id } for { $target } by hand
    .title = Order issued manually!
ntf-paid-order-not-fulfilled = Order #{ $order_id }: { $money } via { $gateway_type } is paid, but no subscription was issued yet; check it.
    .title = Paid order not issued!
    .emoji = ⚠️
ntf-broadcast-completed = Broadcast #{ $broadcast_id } finished: { $sent } delivered, { $failed } failed, { $blocked } blocked the bot.
    .title = Broadcast finished!
ntf-daily-report = { $new_users } new users, { $new_payers } new payers, revenue { $revenue_money }.
    .title = Report for { $day }
    .emoji = 📊
ntf-broadcast-failed = Broadcast #{ $broadcast_id } stopped: { $error }
    .title = Broadcast failed!
    .emoji = ⚠️
ntf-suppressed = { $count } similar alerts since the previous one were not sent.
ntf-sources-merged = Alerts from several sources were merged; the source shown is the last one.
ntf-customer-open-cabinet = Open cabinet
email-login-code = The code is valid for 10 minutes.
    .title = Your sign-in code: { $code }
email-link-code = Enter it in the cabinet to add this email to your account. The code is valid for 10 minutes.
    .title = Your linking code: { $code }
btn-customer-notification =
    .renew = Renew subscription
    .renew-icon = 🔄
    .buy = Buy subscription
    .buy-icon = 💳
    .menu = Go to purchase
    .menu-icon = 💳
    .close = Close
    .close-icon = ❌
    .connect = Connect
    .connect-icon = 🚀
    .support = Contact support
    .support-icon = 📩
    .revoke-sessions = End all sessions
    .revoke-sessions-icon = 🔒
ntf-customer-sessions-revoked = ✅ We've signed you out of every session in your account. If that sign-in wasn't you, contact support and we'll look into it.
ntf-customer-subscription-purchased = To start using the service, connect a device and follow the instructions — it takes a couple of minutes.
    .title = { $is_trial ->
        [yes] Trial activated
       *[no] { $paid ->
            [yes] Payment successful!
           *[no] Subscription activated
        }
    }
    .emoji = { $is_trial ->
        [yes] 🎁
       *[no] ✅
    }
ntf-customer-subscription-renewed = { $duration_days ->
        [0] Your subscription no longer expires.
       *[other] Your subscription was extended by { $duration_days ->
            [one] { $duration_days } day
           *[other] { $duration_days } days
        }.
    }
    .title = { $paid ->
        [yes] Payment successful!
       *[no] Subscription renewed
    }
    .emoji = ✅
ntf-customer-subscription-changed = { $has_plan_name ->
        [yes] Your subscription was moved to the “{ $plan_name }” plan.
       *[other] Your subscription was changed.
    } The connection stays the same, nothing to set up.
    .title = { $paid ->
        [yes] Payment successful!
       *[no] Plan changed
    }
    .emoji = ✅
ntf-customer-subscription-add-on-granted = { $addon_type ->
        [TRAFFIC] { $amount } GB of traffic was added to your subscription.
       *[DEVICES] { $amount ->
            [one] { $amount } device
           *[other] { $amount } devices
        } added to your subscription.
    }
    .title = Add-on activated
    .emoji = 🎁
ntf-customer-subscription-granted = { $has_plan_name ->
        [yes] “{ $plan_name }” subscription
       *[other] Subscription
    } { $duration_days ->
        [0] forever.
       *[other] for { $duration_days ->
            [one] { $duration_days } day
           *[other] { $duration_days } days
        }.
    } Connect a device to start using it.
    .title = Subscription granted
    .emoji = 🎁
ntf-customer-transaction-refunded = { $money } will go back the way you paid.
    .title = Payment refunded
    .emoji = 💸
ntf-customer-transaction-partially-refunded = Part of your payment, { $money }, will go back the way you paid.
    .title = Partial refund
    .emoji = 💸
ntf-customer-paid-order-not-fulfilled = We received your payment of { $money }, but the subscription is taking longer than usual. We're already on it: we'll issue the subscription or refund you. If it isn't settled soon, contact support.
    .title = Delivery delayed
    .emoji = ⏳
ntf-customer-subscription-expiring = { $is_trial ->
        [yes] Your trial ends in { $span_unit ->
        [day] { $span ->
            [one] { $span } day
           *[other] { $span } days
        }
       *[hour] { $span } h
    }. Get a subscription to keep your access.
       *[no] Your subscription ends in { $span_unit ->
        [day] { $span ->
            [one] { $span } day
           *[other] { $span } days
        }
       *[hour] { $span } h
    }. Renew it in advance to keep your access.
    }
    .title = { $is_trial ->
        [yes] Trial ending soon
       *[no] Subscription ending soon
    }
    .emoji = ⚠️
ntf-customer-subscription-expired = { $is_trial ->
        [yes] Your trial has ended. Get a subscription to keep using the VPN.
       *[no] Your subscription has expired. Renew it to keep using the VPN.
    }
    .title = { $is_trial ->
        [yes] Trial ended — the VPN isn't working
       *[no] Subscription expired — the VPN isn't working
    }
    .emoji = ⛔
ntf-customer-subscription-grace-started = Your subscription has expired. { $grace_until ->
        [none] Grace access is active
       *[other] Grace access is active until { $grace_until }
    }{ $traffic_unit ->
        [gb]: { $traffic_value } GB
        [mb]: { $traffic_value } MB
       *[none] {""}
    }. Renew to get your plan back.
    .title = Subscription expired
    .emoji = ⏳
ntf-customer-subscription-expiry-disable-warning = { $is_trial ->
        [yes] Your trial has ended, and on { $disable_date } access will be switched off completely. Get a subscription to keep using the VPN.
       *[no] Your subscription has expired, and on { $disable_date } access will be switched off completely. Renew to keep using the VPN.
    }
    .title = Access will be switched off soon
    .emoji = ⚠️
ntf-customer-subscription-traffic-limited = You've used up your traffic. { $is_trial ->
        [yes] Get a subscription to keep using the service.
       *[no] { $traffic_strategy ->
            [DAY] It comes back tomorrow, or renew your subscription to reset it now.
            [WEEK] It comes back at the start of next week, or renew your subscription to reset it now.
            [MONTH] It comes back at the start of next month, or renew your subscription to reset it now.
            [MONTH_ROLLING] It comes back on your monthly reset day, or renew your subscription to reset it now.
           *[NO_RESET] Renew your subscription to reset your traffic and keep using the service.
        }
    }
    .title = Traffic used up — the VPN isn't working
    .emoji = ⛔
ntf-customer-subscription-traffic-threshold = { $percent ->
        [0] Your traffic is running low.
       *[other] You've used { $percent }% of your traffic.
    }{ $reset_date ->
        [none] {""}
       *[other] {" "}It resets on { $reset_date }.
    }{ $is_trial ->
        [yes] {" "}Get a subscription to keep your access.
       *[no] { $can_renew ->
            [yes] {" "}Renew your subscription to restore it now.
           *[no] {""}
        }
    }
    .title = Traffic running low
    .emoji = ⚠️
ntf-customer-cabinet-new-device-sign-in = Someone signed in to your account from IP address { $ip } ({ $browser }). If it wasn't you, end the sessions on all devices and contact support.
    .title = Sign-in from a new device
    .emoji = 🔐
ntf-customer-accounts-merged = The other account's subscriptions, payments and sign-in methods are now here. If it wasn't you, contact support.
    .title = Accounts merged
    .emoji = 🔗
ntf-customer-referral-reward-issued = Your invitee made a payment — you've received { $amount } { $reward_type ->
        [EXTRA_DAYS] { $amount ->
            [one] bonus day
           *[other] bonus days
        }
        [POINTS] { $amount ->
            [one] point
           *[other] points
        }
       *[other] reward
    }. Thanks for inviting!
    .title = You've earned a reward!
    .emoji = 💰
ntf-customer-invitee-reward-issued = You got { $amount } { $reward_type ->
        [EXTRA_DAYS] { $amount ->
            [one] bonus day
           *[other] bonus days
        }
        [POINTS] { $amount ->
            [one] point
           *[other] points
        }
       *[other] reward
    } for joining by invitation.
    .title = Welcome bonus
    .emoji = 🎁
ntf-panel-login-failed = Failed Remnawave panel sign-in as “{ $username }”. IP: { $ip }
    .title = Failed Remnawave panel sign-in!
    .emoji = ⚠️
ntf-panel-login-succeeded = Remnawave panel sign-in as “{ $username }”. IP: { $ip }
    .title = Remnawave panel sign-in!
ntf-rescue-cli-used = { $action ->
        [reset_owner_access] The owner’s access was reset: new password, IP allowlist cleared, sessions, passkeys and linked accounts removed.
        [enable_password_login] Password sign-in was turned on.
        [reset_encrypted_secrets] Every secret stored in the database was erased: enter the bot token, gateway, OAuth, SMTP and captcha credentials again.
       *[restore_backup] The database was restored from a backup.
    }
    .title = Rescue console used!
    .emoji = ⚠️
ntf-required-channel-check-failed = The bot can't check membership in channel { $channel_id }: { $error }. Customers are let through until it's fixed.
    .title = Required channel check failed!
    .emoji = ⚠️
    .hint = Customers are let through until it's fixed.
ntf-telegram-webhook-failed = Telegram webhook error: { $error }
    .title = Telegram webhook error!
    .emoji = ⚠️
ntf-node-connection-lost = Connection to node “{ $node_name }” lost.
    .title = Node connection lost!
    .emoji = ⚠️
ntf-node-connection-restored = Connection to node “{ $node_name }” restored.
    .title = Node connection restored!
ntf-node-traffic-reached = Node “{ $node_name }” reached its traffic limit.
    .title = Node reached its traffic limit!
    .emoji = ⚠️
ntf-node-billing-due = Payment for node “{ $node_name }” at { $provider } is due { $next_billing_at }.
    .title = Node payment due!
ntf-remnawave-unavailable = Connection to Remnawave lost ({ $error }).
    .title = Connection to Remnawave lost!
    .emoji = ⚠️
ntf-remnawave-restored = Connection to Remnawave restored.
    .title = Remnawave connection restored!
ntf-outbox-entry-poisoned = Event { $failed_event } (#{ $outbox_id }) failed after { $attempts } attempts: { $error }
    .title = Event failed to process!
    .emoji = ⚠️
ntf-system-health-degraded = { $kind ->
        [process_down] The { $subject } process is not responding.
        [host_disk_full] The server disk is { $value }% full.
        [host_memory_high] Server memory is { $value }% used.
        [outbox_stuck] The event queue is not being processed: { $value } waiting over 5 minutes.
        [gateway_failures] Payments through { $subject } are failing: { $value } failures in the last hour.
        [smtp_failed] Email is not being sent: the { $subject ->
            [bulk] broadcast SMTP
           *[main] main SMTP
        } answers with an error.
       *[event_loop_lag] The { $subject } process is responding slowly: event loop p99 is { $value } ms.
    }
    .title = Critical system state!
    .emoji = ⚠️
ntf-system-health-restored = { $kind ->
        [process_down] The { $subject } process is running again.
        [host_disk_full] Server disk usage is back to normal.
        [host_memory_high] Server memory usage is back to normal.
        [outbox_stuck] The event queue is being processed again.
        [gateway_failures] Payments through { $subject } go through again.
        [smtp_failed] Email is being sent again: the { $subject ->
            [bulk] broadcast SMTP
           *[main] main SMTP
        } works.
       *[event_loop_lag] The { $subject } process delay is back to normal.
    }
    .title = System state restored!
ntf-remnawave-version-mismatch = Remnawave { $version } is outside the supported range { $supported }.
    .title = Unsupported Remnawave version!
    .emoji = ⚠️
ntf-panel-started = Remnawave panel restarted.
    .title = Remnawave panel started!
ntf-bot-started = Bot @{ $username } started.
    .title = Bot started!
ntf-bot-stopped = Bot stopped.
    .title = Bot stopped!
ntf-telegram-user-registered = New customer { $user } joined via the bot.
    .title = Bot sign-up!
ntf-cabinet-user-registered = New customer { $user } joined via the web cabinet, signed in with { $method ->
        [EMAIL] email
        [GOOGLE] Google
        [YANDEX] Yandex
       *[TELEGRAM] Telegram
    }.
    .title = Cabinet sign-up!
ntf-telegram-registration-blocked = Registration of { $user } via the bot was blocked.
    .title = Bot sign-up blocked!
ntf-cabinet-registration-blocked = Registration of { $user } via the web cabinet was blocked.
    .title = Cabinet sign-up blocked!
ntf-subscription-first-connected = { $user } connected to the VPN for the first time.
    .title = Subscription first connected!
ntf-torrent-blocker-report = Torrent traffic from { $user } blocked on “{ $node_name }” ({ $destination }).
    .title = Torrent traffic blocked!
    .emoji = ⚠️
ntf-subscription-expired = { $user }'s subscription expired.
    .title = Subscription expired!
ntf-subscription-traffic-limited = { $user } ran out of traffic.
    .title = Traffic limit reached!
ntf-subscription-revoked = { $user }'s subscription link was reissued.
    .title = Subscription link reissued!
ntf-subscription-not-connected = { $user } hasn't connected { $hours } h after subscribing.
    .title = Subscription not connected!
ntf-customer-subscription-not-connected = You subscribed { $span_unit ->
        [day] { $span ->
            [one] { $span } day
           *[other] { $span } days
        }
       *[hour] { $span } h
    } ago but haven't used it yet. If setting it up was tricky, contact support — we'll sort it out together.
    .title = Couldn't connect?
    .emoji = 🔌
ntf-customer-subscription-expired-ago = { $is_trial ->
        [yes] Your trial ended { $span_unit ->
        [day] { $span ->
            [one] { $span } day
           *[other] { $span } days
        }
       *[hour] { $span } h
    } ago. Get a subscription to use the VPN again.
       *[no] Your subscription expired { $span_unit ->
        [day] { $span ->
            [one] { $span } day
           *[other] { $span } days
        }
       *[hour] { $span } h
    } ago. Renew it to use the VPN again.
    }
    .title = { $is_trial ->
        [yes] Trial ended — the VPN isn't working
       *[no] Subscription expired — the VPN isn't working
    }
    .emoji = ⛔
ntf-customer-torrent-blocker-report = We noticed torrent traffic over the VPN. Torrents are against the service rules, so your connection is limited{ $block_unit ->
        [minute] { " " }for { $block_span ->
            [one] { $block_span } minute
           *[other] { $block_span } minutes
        }
        [hour] { " " }for { $block_span } h
       *[none] {""}
    }. Turn off your torrent client or exclude it from the VPN so it doesn't happen again. Repeated violations may restrict access permanently.
    .title = Connection temporarily limited
    .emoji = ⛔
ntf-customer-promocode-discount-expiring = Your { $percent }% off with promocode { $code } is valid for { $span_unit ->
        [day] { $span ->
            [one] { $span } more day
           *[other] { $span } more days
        }
        [minute] { $span ->
            [one] { $span } more minute
           *[other] { $span } more minutes
        }
       *[hour] { $span ->
            [one] { $span } more hour
           *[other] { $span } more hours
        }
    }. Make your purchase before it’s gone.
    .title = Your discount is about to expire
    .emoji = ⏳
ntf-customer-payments-restored = Payments are back! You can now buy or renew a subscription. Thanks for waiting.
    .title = Payments are back
    .emoji = ❇️
ntf-telegram-label =
    .event = Event
    .user = User
    .id = ID
    .telegram-id = Telegram ID
    .name = Name
    .username = Username
    .email = Email
    .details = Details
    .payment = Payment
    .subscription = Subscription
    .trial-subscription = Trial subscription
    .plan = Plan
    .trial-plan = Trial plan
    .promocode = Promocode
    .device = Device
    .build = Build
    .access = Access
    .session = Session
    .order = Order
    .ip = IP
    .login = Login
    .method = Method
    .provider = Provider
    .user-agent = User agent
    .kind = Type
    .run = Run
    .bonus-days = Bonus days
    .channel = Channel
    .error = Error
    .node = Node
    .reason = Reason
    .billing-date = Billing date
    .version = Version
    .supported = Supported
    .bot = Bot
    .broadcast = Broadcast
    .sent = Delivered
    .failed = Failed
    .blocked = Blocked the bot
    .admin = Admin
    .previous-status = Previous status
    .ad-link = Ad link
    .referral-code = Referral code
    .sign-in-method = Sign-in method
    .hours = Hours passed
    .destination = Destination
    .payment-method = Payment method
    .amount = Amount
    .refund = Refund
    .status = Status
    .traffic = Traffic
    .traffic-limit = Traffic limit
    .device-limit = Device limit
    .left = Left
    .duration = Duration
    .type = Type
    .code = Code
    .reward = Reward
    .branch = Branch
    .commit = Commit
    .build-time = Build time
    .mode = Mode
    .payments = Payments
    .registration = Registration
    .uptime = Uptime
    .hwid = HWID
    .platform = Platform
    .model = Model
    .os-version = OS version
    .channel-bot = Bot
    .channel-cabinet = Web cabinet
    .method-password = Password
    .method-passkey = Passkey
    .method-oauth = OAuth
    .refund-full = full
    .refund-partial = partial
    .unlimited = Unlimited
    .report-day = For the day
    .new-users = New users
    .new-trials = New trials
    .trial-conversions = Trial → paid
    .new-payers = New payers
    .revenue = Revenue
    .report-subscriptions = Subscriptions now
    .active-trials = Active trials
    .active-paid = Active paid
    .paid-never-connected = Paid, never connected
    .report-payments = Payments
    .purchases = Purchases
    .renewals = Renewals
    .changes = Plan changes
    .report-referrers = Top referrers
    .unnamed-user = User
ntf-telegram-subscription-status = { $value ->
        [ACTIVE] Active
        [LIMITED] Out of traffic
        [EXPIRED] Expired
        [DISABLED] Disabled
        [DELETED] Deleted
       *[other] { $value }
    }
ntf-telegram-plan-type = { $value ->
        [TRAFFIC] Traffic
        [DEVICES] Devices
        [BOTH] Traffic + devices
       *[UNLIMITED] Unlimited
    }
ntf-telegram-transaction-status = { $value ->
        [PENDING] Awaiting payment
        [PAID] Paid
        [FAILED] Issue failed
        [CANCELED] Canceled
        [REFUNDED] Refunded
       *[other] { $value }
    }
ntf-telegram-backup-kind = { $value ->
        [DATABASE] Database
        [ASSETS] Files
       *[other] { $value }
    }
ntf-telegram-sign-in-method = { $value ->
        [TELEGRAM] Telegram
        [EMAIL] Email
        [GOOGLE] Google
        [YANDEX] Yandex
       *[other] { $value }
    }
ntf-telegram-oauth-provider = { $value ->
        [GITHUB] GitHub
        [TELEGRAM] Telegram
        [OIDC] OIDC
        [GOOGLE] Google
        [YANDEX] Yandex
       *[other] { $value }
    }
ntf-telegram-access-mode = { $value ->
        [PUBLIC] open to everyone
        [INVITED] invited only
        [RESTRICTED] closed to everyone
       *[other] { $value }
    }
ntf-telegram-payments = { $value ->
        [yes] allowed
       *[no] disabled
    }
ntf-telegram-registration = { $value ->
        [yes] allowed
       *[no] disabled
    }
ntf-telegram-promocode-type = { $value ->
        [DURATION] Duration
        [TRAFFIC] Traffic
        [DEVICES] Devices
        [SUBSCRIPTION] Subscription
        [PERSONAL_DISCOUNT] Personal discount
        [PURCHASE_DISCOUNT] Purchase discount
       *[other] { $value }
    }
ntf-telegram-unlimited = no end date
ntf-telegram-days = { $count ->
        [one] { $count } day
       *[other] { $count } days
    }
ntf-telegram-uptime = { $days ->
        [0] { $hours } h { $minutes } min
       *[other] { $days } d { $hours } h
    }
ntf-telegram-traffic = { $unit ->
        [MB] { $amount } MB
        [TB] { $amount } TB
       *[GB] { $amount } GB
    }
ntf-subscription-changed = { $user } changed their subscription plan.
    .title = Subscription plan changed!
ntf-subscription-device-added = { $user } added a new device.
    .title = Device added!
ntf-subscription-device-removed = { $user } removed a device.
    .title = Device removed!
ntf-promocode-activated = { $user } activated a promocode.
    .title = Promocode activated!
ntf-customer-referral-attached = Someone joined through your invite link.{ $rewarded ->
        [yes] { " " }You'll get your reward once they pay for a subscription.
       *[no] {""}
    }
    .title = You invited a friend!
    .emoji = 🎉

ntf-recurring-reason = { $reason ->
    [admin_closed] payment waiting was closed by an administrator
    [customer_disabled] auto-renewal was disabled by the customer
    [bank_declined] the bank declined the payment
    [insufficient_funds] insufficient funds
    [issuer_unavailable] the issuing bank is temporarily unavailable
    [payment_method_unavailable] the payment method is temporarily unavailable
    [provider_unavailable] the payment provider is unavailable
    [merchant_unavailable] the shop cannot process payments
    [provider_configuration_error] the payment or receipt configuration requires correction
    [provider_request_rejected] YooKassa refused the charge to the saved card: the card was declined or the shop settings are wrong
    [provider_rejected] the payment provider rejected the request
    [permission_revoked] the payment provider mandate was revoked
    [payment_method_restricted] the saved payment method is no longer valid
    [card_expired] the card has expired
    [fraud_suspected] the bank blocked the payment
    [price_changed] the price exceeds the agreed limit
    [subscription_changed] the subscription terms changed
    [shop_changed] the payment shop changed
    [consent_required] consent to renewal terms is required
    [plan_unavailable] the plan is not available for purchase
    [customer_email_required] an email address is required for the receipt
    [gateway_disabled] the shop disabled recurring payments
    [subscription_unavailable] the subscription cannot be renewed
    [payment_status_unknown] the previous payment outcome is unknown
    [pending_timeout] the payment has been pending too long
    [retries_exhausted] payment retries were exhausted
    [payment_method_not_saved] the payment provider did not save the payment method
    [renewal_window_expired] the agreed renewal retry window expired
    [refunded] a payment for the subscription was refunded
   *[other] there was an issue with automatic payment
    }
ntf-recurring-payment-upcoming = Subscription #{ $subscription_id }: a charge of up to { $amount } { $currency } is scheduled for { $scheduled_at }.
    .title = Upcoming automatic payment
ntf-recurring-payment-failed = Subscription #{ $subscription_id }, order #{ $order_id }: attempt #{ $attempt } failed because { $reason_text }.
    .title = Automatic payment failed
ntf-recurring-payment-paused = Subscription #{ $subscription_id }: automatic payments paused because { $reason_text }.
    .title = Auto-renewal needs attention
ntf-recurring-payment-exhausted = Subscription #{ $subscription_id }: payment retries ended because { $reason_text }. Manual renewal is required.
    .title = Automatic renewal failed
ntf-customer-recurring-payment-upcoming = An automatic charge of up to { $money } for subscription #{ $subscription_id } is scheduled for { $scheduled_at }. Check your balance. You can stop future charges in this subscription's settings in the bot.
    .title = Your subscription will renew soon
ntf-customer-recurring-payment-failed = We could not automatically pay for your subscription because { $reason_text }. { $has_next_attempt ->
    [yes] Next attempt: { $next_attempt_at }.
   *[no] Another attempt has not been scheduled yet.
    } Check your balance or renew manually.
    .title = Automatic payment failed
ntf-customer-recurring-payment-paused = Automatic renewal is paused because { $reason_text }. { $has_next_attempt ->
    [yes] The next check is scheduled for { $next_attempt_at }.
   *[no] Check your subscription settings or contact support.
    } Your paid period remains available.
    .title = Check your auto-renewal settings
ntf-customer-recurring-payment-exhausted = We could not automatically renew your subscription because { $reason_text }. Automatic renewal has stopped. Renew manually to keep your access.
    .title = Your subscription needs renewal
# the payment page and the fiscal receipt name the order with this
payment-description = Subscription “{ $plan }”, { $period }
payment-period = { $unit ->
    [unlimited] forever
    [year] { $value ->
        [one] { $value } year
       *[other] { $value } years
    }
    [month] { $value ->
        [one] { $value } month
       *[other] { $value } months
    }
   *[day] { $value ->
        [one] { $value } day
       *[other] { $value } days
    }
}
# auto-renewal terms the customer accepts; the accepted text is stored with the consent
recurring-terms-summary = With your consent, auto-renewal saves your payment method with YooKassa and authorizes automatic charges up to { $amount } { $currency } every { $days } days, starting { $lead_minutes } min. before expiry. Stop future charges in your subscription settings in the bot or the web account.
recurring-terms-text =
    Automatic renewal terms

    Current payment: { $initial } { $currency }.
    Renewals: up to { $amount } { $currency } every { $days } days. One-time discounts do not apply to renewals. Charges stop if the price exceeds this limit or the plan terms change.

    Payment starts { $lead_minutes } min. before the paid period expires. A bank decline may be retried at { $retry_hours } hours from the first failure, within the agreed window. A temporary failure may be retried every { $retry_minutes } min.; new attempts stop { $overdue_hours } hours after expiry. A payment already submitted may complete later.

    By consenting, you authorize saving your payment method through YooKassa and using it to renew this subscription without confirming each charge.

    Withdraw consent and stop future charges with Disable auto-renewal in your subscription settings in the bot or the web account. Withdrawal stops new attempts; a payment already submitted may complete. Your paid period remains available. The saved payment method is deleted { $retention_days } days after withdrawal. Reconnection requires fresh explicit consent.
