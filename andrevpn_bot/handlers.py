from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message, PreCheckoutQuery

from .config import Config, Plan
from .db import ActiveSubscriptionError, Database, TrialAlreadyUsedError
from .keyboards import (
    admin_back_menu,
    admin_menu,
    back_menu,
    instruction_done_menu,
    instructions_android_menu,
    instructions_back_menu,
    instructions_ios_menu,
    instructions_os_menu,
    main_menu,
    payment_method_menu,
    plans_menu,
    sbp_payment_menu,
    sbp_plans_menu,
    support_menu,
    trial_menu,
)
from .payments import PaidSubscriptionService
from .referrals import ReferralGrant, ReferralService
from .texts import cabinet, connection_link_message, connection_text, format_dt, trial_success_text, trial_text, welcome
from .xui import XuiApi, XuiError
from .yookassa import YookassaError, YookassaPaymentService, YookassaVerificationError


WELCOME_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "welcome.png"
HAPP_STEPS = (
    (
        "Установите приложение Happ - Proxy Utility",
        Path(__file__).resolve().parent.parent / "assets" / "happ_step_3.jpg",
    ),
    (
        'В боте откройте раздел "Получить подключение" и скопируйте персональную ссылку',
        Path(__file__).resolve().parent.parent / "assets" / "happ_step_2.jpg",
    ),
    (
        'Зайдите в Happ - Proxy Utility и нажмите "Из Буфера" -> Разрешить Вставку',
        Path(__file__).resolve().parent.parent / "assets" / "happ_step_1.jpg",
    ),
)
ANDROID_HAPP_STEPS = (
    (
        "Установите приложение Happ - Proxy Utility",
        Path(__file__).resolve().parent.parent / "assets" / "android_happ_step_1.png",
    ),
    *HAPP_STEPS[1:],
)
GOOGLEPLAY_HAPP_STEP = (
    "Google Play может удалить HAPP из Play Market, из-за этого нужно скачать приложение напрямую.\n\n"
    'Перейдите по ссылке: <a href="https://www.happ.su/main/ru">https://www.happ.su/main/ru</a> '
    'и выберите под пунктом Android "Download APK". Начнется скачивание установочного файла. '
    "После скачивания установите его. HAPP должен появиться у вас на телефоне.",
    Path(__file__).resolve().parent.parent / "assets" / "googleplay_happ_apk.png",
)
APPSTORE_STEPS = (
    (
        "1. В данный момент Happ недоступен в Российском App Store. Но в зарубежном он есть. "
        "Чтобы у вас появились недоступные приложения нужно поменять регион. "
        "Так же появятся приложения такие как ChatGPT, Google Gemini, Grok и т.д. "
        "Для этого перейдите в свой аккаунт App Store.",
        Path(__file__).resolve().parent.parent / "assets" / "appstore_step_1.jpg",
    ),
    (
        "2. Перейдите в управление аккаунтом.",
        Path(__file__).resolve().parent.parent / "assets" / "appstore_step_2.jpg",
    ),
    (
        '3. Выберите пункт "Страна и регион", найдите и выберите "Соединенные штаты".',
        Path(__file__).resolve().parent.parent / "assets" / "appstore_step_3.jpg",
    ),
    (
        "4. Введите эти данные. Эти данные сгенерированы и не существующие. "
        "Либо можно сгенерировать свои данные и ввести их.",
        Path(__file__).resolve().parent.parent / "assets" / "appstore_step_4.jpg",
    ),
    (
        "5. Готово! Сейчас перейдите в поиск приложений и у вас появится приложение HAPP, v2RayTun, AI приложения.",
        None,
    ),
)


def build_router(config: Config, db: Database, xui: XuiApi) -> Router:
    router = Router()
    referrals = ReferralService(db)
    paid_subscriptions = PaidSubscriptionService(db, referrals)
    yookassa = YookassaPaymentService(config, db) if config.yookassa_enabled else None
    admin_add_waiting: set[int] = set()
    support_waiting: set[int] = set()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        is_new_user = not db.user_exists(message.from_user.id)
        user = db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        user = referrals.ensure_referral_code(user)
        referrals.bind_from_start_argument(user, _start_argument(message.text), is_new_user=is_new_user)
        if is_new_user:
            await _notify_admins(
                message.bot,
                config,
                (
                    "<b>Новый клиент</b>\n"
                    f"ID: <code>{message.from_user.id}</code>\n"
                    f"Username: @{message.from_user.username}" if message.from_user.username else
                    f"<b>Новый клиент</b>\nID: <code>{message.from_user.id}</code>\nUsername: нет"
                ),
            )
        await _send_home(message, config, message.from_user.id)

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        admin_add_waiting.discard(callback.from_user.id)
        support_waiting.discard(callback.from_user.id)
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await _send_home(callback.message, config, callback.from_user.id)

    @router.callback_query(F.data == "admin")
    async def admin_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        admin_add_waiting.discard(callback.from_user.id)
        await _show_section(
            callback,
            "<b>Админ панель ANDREVPN</b>\n\nВыберите нужный раздел.",
            admin_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:stats")
    async def admin_stats_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        await _show_section(callback, _admin_stats_text(db, config), admin_back_menu())
        await callback.answer()

    @router.callback_query(F.data == "admin:add")
    async def admin_add_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        admin_add_waiting.add(callback.from_user.id)
        await _show_section(
            callback,
            (
                "<b>Добавить подписку по Telegram ID</b>\n\n"
                "Отправьте следующим сообщением ID пользователя и срок в днях.\n\n"
                "Пример:\n<code>443060337 30</code>\n\n"
                "Бот создаст пользователя, продлит подписку и добавит клиента во все VPN-профили."
            ),
            admin_back_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:server")
    async def admin_server_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        await _show_section(callback, _server_status_text(), admin_back_menu())
        await callback.answer()

    @router.callback_query(F.data == "cabinet")
    async def cabinet_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        await _show_section(callback, cabinet(user), back_menu())
        await callback.answer()

    @router.callback_query(F.data == "referrals")
    async def referrals_handler(callback: CallbackQuery) -> None:
        user = referrals.ensure_referral_code(_touch_user(callback, db))
        bot_info = await callback.bot.get_me()
        if not bot_info.username:
            await callback.answer("Не удалось получить имя бота.", show_alert=True)
            return
        link = referrals.referral_link(user, bot_info.username)
        await _show_section(callback, _referral_program_text(user, link, referrals.stats(user)), back_menu())
        await callback.answer()

    @router.callback_query(F.data == "support")
    async def support_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        support_waiting.add(user.telegram_id)
        await _show_section(
            callback,
            (
                "<b>Вопросы и Поддержка</b>\n\n"
                "Опишите вопрос одним или несколькими сообщениями. "
                "Можно отправить текст, скриншот или фото ошибки.\n\n"
                "Ваше обращение будет передано в поддержку."
            ),
            support_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "instructions")
    async def instructions_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await _show_section(
            callback,
            "<b>Инструкция по подключению</b>\n\nВыберите операционную систему.",
            instructions_os_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "instructions:android")
    async def instructions_android_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await _show_section(
            callback,
            "<b>Android</b>\n\nВыберите нужный раздел.",
            instructions_android_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "instructions:android:happ")
    async def instructions_android_happ_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(
            callback,
            "<b>Как подключить подписку к HAPP</b>\n\nИнструкция отправлена сообщениями ниже.",
            instructions_android_menu(),
        )
        if callback.message:
            await _send_happ_instruction(callback.message, ANDROID_HAPP_STEPS)

    @router.callback_query(F.data == "instructions:android:googleplay")
    async def instructions_android_googleplay_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await _show_section(
            callback,
            "<b>Что делать если в Google Play нет HAPP</b>\n\nИнструкция отправлена сообщением ниже.",
            instructions_android_menu(),
        )
        await callback.answer()
        if callback.message:
            await _send_googleplay_instruction(callback.message)

    @router.callback_query(F.data == "instructions:ios")
    async def instructions_ios_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await _show_section(
            callback,
            "<b>IOS</b>\n\nВыберите нужный раздел.",
            instructions_ios_menu(),
        )
        await callback.answer()

    @router.callback_query(F.data == "instructions:ios:happ")
    async def happ_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(
            callback,
            "<b>Как подключить подписку к HAPP</b>\n\nИнструкция отправлена сообщениями ниже.",
            instructions_ios_menu(),
        )
        if callback.message:
            await _send_happ_instruction(callback.message)

    @router.callback_query(F.data == "instructions:ios:appstore")
    async def instructions_ios_appstore_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await _show_section(
            callback,
            "<b>Что делать если в App Store нет HAPP</b>\n\nИнструкция отправлена сообщениями ниже.",
            instructions_ios_menu(),
        )
        await callback.answer()
        if callback.message:
            await _send_appstore_instruction(callback.message)

    @router.callback_query(F.data == "trial")
    async def trial_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        keyboard = trial_menu() if user.trial_used_at is None and not user.is_active else back_menu()
        await _show_section(callback, trial_text(user), keyboard)
        await callback.answer()

    @router.callback_query(F.data == "trial:activate")
    async def trial_activate_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        try:
            updated_user = db.activate_trial(user.telegram_id, days=3)
        except TrialAlreadyUsedError:
            await _show_section(callback, trial_text(db.get_user(user.telegram_id)), back_menu())
            await callback.answer("Пробный период уже был использован.", show_alert=True)
            return
        except ActiveSubscriptionError:
            await _show_section(callback, trial_text(db.get_user(user.telegram_id)), back_menu())
            await callback.answer("У вас уже есть активная подписка.", show_alert=True)
            return

        try:
            await xui.provision_user(db, updated_user)
            updated_user = db.get_user(user.telegram_id)
        except XuiError as exc:
            await callback.answer("Пробная подписка активирована, но подключение создаётся вручную.", show_alert=True)
            await _notify_admins(callback.message.bot, config, f"Trial user {user.telegram_id}, but 3X-UI failed: {exc}")
            return

        await _show_section(callback, trial_success_text(updated_user), back_menu())
        await callback.answer("Пробная подписка активирована.")
        referral_grant = referrals.grant_trial_reward(updated_user)
        if referral_grant:
            await _notify_referral_grant(callback.message.bot, referral_grant, "trial")
        await _notify_admins(
            callback.message.bot,
            config,
            f"<b>Пробная подписка</b>\nID: <code>{user.telegram_id}</code>\nСрок: 3 дня",
        )

    @router.callback_query(F.data == "connection")
    async def connection_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        if user.is_active:
            try:
                await xui.provision_user(db, user)
                user = db.get_user(user.telegram_id)
            except XuiError as exc:
                await callback.answer("Не удалось создать подключение, администратор уже получил ошибку.", show_alert=True)
                await _notify_admins(callback.message.bot, config, f"3X-UI error for {user.telegram_id}: {exc}")
                return

        await callback.answer()
        await _show_section(callback, connection_text(user, config), back_menu())
        link_message = connection_link_message(user, config)
        if link_message and callback.message:
            await callback.message.answer(link_message)

    @router.callback_query(F.data == "plans")
    async def plans_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await _show_section(
            callback,
            "<b>Оплатить / продлить</b>\n\nВыберите способ оплаты.",
            payment_method_menu(config.yookassa_enabled),
        )
        await callback.answer()

    @router.callback_query(F.data == "plans:stars")
    async def stars_plans_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await _show_section(
            callback,
            "<b>TG звездами (автоматически)</b>\n\nВыберите срок подписки.",
            plans_menu(config.plans, config.payment_currency, back_callback="plans"),
        )
        await callback.answer()

    @router.callback_query(F.data == "plans:sbp")
    async def sbp_plans_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        if yookassa is None:
            await _show_section(
                callback,
                "<b>СБП через ЮKassa</b>\n\nОплата через СБП временно недоступна.",
                back_menu(),
            )
            await callback.answer()
            return
        await _show_section(
            callback,
            "<b>СБП через ЮKassa</b>\n\nВыберите срок подписки.",
            sbp_plans_menu(config.sbp_plans),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("sbp:create:"))
    async def sbp_create_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        if yookassa is None:
            await callback.answer("СБП временно недоступна.", show_alert=True)
            return
        code = callback.data.split(":", 2)[2]
        try:
            plan = _find_plan(config.sbp_plans, code)
            order = await yookassa.create_sbp_payment(user, plan)
        except (RuntimeError, YookassaError) as exc:
            await _show_section(
                callback,
                (
                    "<b>СБП через ЮKassa</b>\n\n"
                    "Не удалось создать платёж. Попробуйте ещё раз чуть позже."
                ),
                sbp_plans_menu(config.sbp_plans),
            )
            await callback.answer("Платёж не создан.", show_alert=True)
            await _notify_admins(callback.message.bot, config, f"YooKassa create payment error for {user.telegram_id}: {exc}")
            return
        if not order.confirmation_url:
            await callback.answer("ЮKassa не вернула ссылку оплаты.", show_alert=True)
            return

        await _show_section(callback, _sbp_order_text(order, config), sbp_payment_menu(order.id, order.confirmation_url))
        await callback.answer()

    @router.callback_query(F.data.startswith("sbp:check:"))
    async def sbp_check_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        if yookassa is None:
            await callback.answer("СБП временно недоступна.", show_alert=True)
            return
        try:
            order_id = int(callback.data.split(":", 2)[2])
            result = await yookassa.check_order(order_id)
        except (ValueError, LookupError):
            await callback.answer("Неизвестный тариф.", show_alert=True)
            return
        except YookassaVerificationError as exc:
            await callback.answer("Платёж не прошёл проверку.", show_alert=True)
            await _notify_admins(callback.message.bot, config, f"YooKassa verification error: {exc}")
            return
        except YookassaError as exc:
            await callback.answer("Не удалось проверить оплату. Попробуйте чуть позже.", show_alert=True)
            await _notify_admins(callback.message.bot, config, f"YooKassa check error: {exc}")
            return

        if result.status == "pending":
            await callback.answer("Оплата ещё не подтверждена.", show_alert=True)
            return
        if result.status == "canceled":
            await _show_section(
                callback,
                "<b>Платёж отменён</b>\n\nСоздайте новый платёж и попробуйте снова.",
                sbp_plans_menu(config.sbp_plans),
            )
            await callback.answer()
            return
        if result.status != "succeeded" or result.finalization is None:
            await callback.answer("Платёж пока не подтверждён.", show_alert=True)
            return

        if not result.finalization.already_processed:
            await _after_successful_external_payment(
                callback.message.bot,
                config,
                db,
                xui,
                yookassa,
                result.finalization,
            )
        await _show_section(
            callback,
            "Оплата подтверждена. Подписка ANDREVPN продлена.\n\n" + cabinet(result.finalization.user),
            main_menu(_is_admin(callback.from_user.id, config)),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("pay:"))
    async def pay_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        plan = _find_plan(config.plans, callback.data.split(":", 1)[1])

        is_stars_payment = config.payment_currency.upper() == "XTR"
        if not is_stars_payment and not config.payment_provider_token:
            text = (
                "<b>Оплата пока не подключена</b>\n\n"
                "Тариф выбран, но платёжный токен ещё не указан в настройках бота. "
                "Напишите администратору для ручного продления."
            )
            await _show_section(callback, text, back_menu())
            await callback.answer()
            await _notify_admins(callback.message.bot, config, f"User {user.telegram_id} wants to pay for {plan.title}")
            return

        invoice = {
            "title": f"{config.payment_title}: {plan.title}",
            "description": f"{config.payment_description}. Срок: {plan.days} дней.",
            "payload": f"plan:{plan.code}",
            "currency": config.payment_currency,
            "prices": [LabeledPrice(label=plan.title, amount=_telegram_amount(plan, config.payment_currency))],
        }
        if not is_stars_payment:
            invoice["provider_token"] = config.payment_provider_token

        await callback.message.answer_invoice(**invoice)
        await callback.answer()

    @router.pre_checkout_query()
    async def pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
        await pre_checkout_query.answer(ok=True)

    @router.message(F.successful_payment)
    async def successful_payment(message: Message) -> None:
        if message.from_user is None or message.successful_payment is None:
            return

        user = db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        payload = message.successful_payment.invoice_payload
        plan_code = payload.split(":", 1)[1] if payload.startswith("plan:") else ""
        plan = _find_plan(config.plans, plan_code)

        result = paid_subscriptions.confirm_payment_and_extend_subscription(
            user=user,
            plan=plan,
            amount=message.successful_payment.total_amount,
            currency=message.successful_payment.currency,
            provider="telegram_stars" if message.successful_payment.currency.upper() == "XTR" else "telegram_payment",
            provider_payment_charge_id=message.successful_payment.provider_payment_charge_id,
            telegram_payment_charge_id=message.successful_payment.telegram_payment_charge_id,
            raw_payload=json.dumps(message.successful_payment.model_dump(mode="json"), ensure_ascii=False),
        )
        updated_user = result.user

        try:
            await xui.provision_user(db, updated_user)
            updated_user = db.get_user(user.telegram_id)
        except XuiError as exc:
            await _notify_admins(message.bot, config, f"Paid user {user.telegram_id}, but 3X-UI failed: {exc}")
            await message.answer(
                "Оплата прошла, подписка продлена. Подключение создаётся вручную администратором.",
                reply_markup=main_menu(_is_admin(user.telegram_id, config)),
            )
            return

        if result.referral_grant:
            await _notify_referral_grant(message.bot, result.referral_grant, "payment")

        await message.answer(
            "Оплата прошла успешно. Подписка ANDREVPN продлена.\n\n" + cabinet(updated_user),
            reply_markup=main_menu(_is_admin(user.telegram_id, config)),
        )
        await _notify_admins(
            message.bot,
            config,
            (
                "<b>Продление подписки</b>\n"
                f"ID: <code>{user.telegram_id}</code>\n"
                f"Тариф: {plan.title}\n"
                f"Сумма: {message.successful_payment.total_amount} {message.successful_payment.currency}\n"
                f"Активна до: <b>{format_dt(updated_user.subscription_until)}</b>"
            ),
        )

    @router.message(
        lambda message: message.from_user is not None
        and message.from_user.id in support_waiting
        and message.from_user.id not in admin_add_waiting
    )
    async def support_message_handler(message: Message) -> None:
        if message.from_user is None:
            return

        user = db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await _notify_support_message(message, config, user)
        await message.answer(
            (
                "Сообщение отправлено в поддержку.\n\n"
                "Если нужно, отправьте еще один скриншот или дополнительный текст. "
                "Чтобы выйти, нажмите кнопку ниже."
            ),
            reply_markup=support_menu(),
        )

    @router.message(F.text)
    async def admin_text_handler(message: Message) -> None:
        if message.from_user is None or not _is_admin(message.from_user.id, config):
            return
        if message.from_user.id not in admin_add_waiting:
            return

        try:
            telegram_id, days = _parse_admin_add_request(message.text or "")
        except ValueError:
            await message.answer(
                "Не понял формат. Отправьте так:\n<code>443060337 30</code>",
                reply_markup=admin_back_menu(),
            )
            return

        user = db.get_or_create_user(telegram_id)
        updated_user = db.extend_subscription(user.telegram_id, days)
        try:
            await xui.provision_user(db, updated_user)
            updated_user = db.get_user(user.telegram_id)
        except XuiError as exc:
            await message.answer(
                f"Подписка продлена, но подключение в 3X-UI не создалось:\n<code>{exc}</code>",
                reply_markup=admin_back_menu(),
            )
            return

        admin_add_waiting.discard(message.from_user.id)
        await message.answer(
            (
                "<b>Подписка добавлена</b>\n\n"
                f"ID: <code>{updated_user.telegram_id}</code>\n"
                f"Срок: {days} дней\n"
                f"{cabinet(updated_user)}"
            ),
            reply_markup=admin_back_menu(),
        )
        await _notify_user_about_admin_subscription(message.bot, updated_user, days)
        await _notify_admins(
            message.bot,
            config,
            (
                "<b>Ручная выдача подписки</b>\n"
                f"ID: <code>{updated_user.telegram_id}</code>\n"
                f"Срок: {days} дней"
            ),
        )

    return router


def _touch_user(callback: CallbackQuery, db: Database):
    if callback.from_user is None:
        raise RuntimeError("Callback without Telegram user")
    return db.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)


def _start_argument(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else None


def _referral_program_text(user, referral_link: str, stats: dict[str, int]) -> str:
    referrer = f"<code>{user.referred_by}</code>" if user.referred_by else "нет"
    return (
        "<b>Реферальная программа</b>\n\n"
        "Приглашайте друзей и получайте бонусные дни к VPN:\n\n"
        "Друг запустил пробный период - <b>+3 дня</b>\n"
        "Друг купил 1 месяц - <b>+7 дней</b>\n"
        "Друг купил 2 месяца - <b>+14 дней</b>\n"
        "Друг купил 3 месяца - <b>+21 день</b>\n\n"
        "Ваша ссылка:\n"
        f"<code>{referral_link}</code>\n\n"
        f"Приглашено пользователей: <b>{stats['invited_users']}</b>\n"
        f"Начислено бонусных дней: <b>{stats['reward_days']}</b>\n"
        f"Бонусов за пробный период: <b>{stats['trial_rewards']}</b>\n"
        f"Бонусов за оплаты: <b>{stats['payment_rewards']}</b>\n\n"
        f"Вас пригласил: {referrer}"
    )


def _sbp_order_text(order, config: Config) -> str:
    try:
        title = _find_plan(config.sbp_plans, order.plan_code).title
    except RuntimeError:
        title = order.plan_code
    return (
        "<b>СБП через ЮKassa</b>\n\n"
        f"Тариф: <b>{title}</b>\n"
        f"Сумма: <b>{_format_rub_kopecks(order.amount_kopecks)}</b>\n\n"
        "Нажмите кнопку <b>Оплатить через СБП</b>. После оплаты вернитесь в Telegram "
        "и нажмите <b>Проверить оплату</b>."
    )


async def _after_successful_external_payment(
    bot,
    config: Config,
    db: Database,
    xui: XuiApi,
    yookassa: YookassaPaymentService,
    finalization,
) -> None:
    updated_user = finalization.user
    try:
        await xui.provision_user(db, updated_user)
        updated_user = db.get_user(updated_user.telegram_id)
    except XuiError as exc:
        await _notify_admins(bot, config, f"Paid YooKassa user {updated_user.telegram_id}, but 3X-UI failed: {exc}")

    try:
        await bot.send_message(
            updated_user.telegram_id,
            "Оплата через СБП прошла успешно. Подписка ANDREVPN продлена.\n\n" + cabinet(updated_user),
            reply_markup=main_menu(_is_admin(updated_user.telegram_id, config)),
        )
    except Exception:
        pass

    referral_grant = yookassa.referral_grant(finalization)
    if referral_grant:
        await _notify_referral_grant(bot, referral_grant, "payment")

    await _notify_admins(
        bot,
        config,
        (
            "<b>Оплата через СБП</b>\n"
            f"ID: <code>{updated_user.telegram_id}</code>\n"
            f"Тариф: {finalization.order.plan_code}\n"
            f"Сумма: {_format_rub_kopecks(finalization.order.amount_kopecks)}\n"
            f"Активна до: <b>{format_dt(updated_user.subscription_until)}</b>"
        ),
    )


def _format_rub_kopecks(amount_kopecks: int) -> str:
    rubles, kopecks = divmod(amount_kopecks, 100)
    if kopecks:
        return f"{rubles},{kopecks:02d} ₽"
    return f"{rubles} ₽"


async def _show_section(callback: CallbackQuery, text: str, reply_markup) -> None:
    if callback.message is None:
        return
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=reply_markup)
        return
    await callback.message.edit_text(text, reply_markup=reply_markup)


async def _send_home(message: Message, config: Config, user_id: int | None = None) -> None:
    keyboard = main_menu(_is_admin(user_id, config))
    if WELCOME_IMAGE_PATH.exists():
        await message.answer_photo(
            FSInputFile(WELCOME_IMAGE_PATH),
            caption=welcome(config),
            reply_markup=keyboard,
        )
        return
    await message.answer(welcome(config), reply_markup=keyboard)


async def _send_happ_instruction(message: Message, steps=HAPP_STEPS) -> None:
    for index, (caption, image_path) in enumerate(steps):
        reply_markup = instruction_done_menu() if index == len(steps) - 1 else None
        if image_path.exists():
            await message.answer_photo(FSInputFile(image_path), caption=caption, reply_markup=reply_markup)
        else:
            await message.answer(caption, reply_markup=reply_markup)


async def _send_appstore_instruction(message: Message) -> None:
    for index, (caption, image_path) in enumerate(APPSTORE_STEPS):
        reply_markup = instruction_done_menu() if index == len(APPSTORE_STEPS) - 1 else None
        if image_path and image_path.exists():
            await message.answer_photo(FSInputFile(image_path), caption=caption, reply_markup=reply_markup)
        else:
            await message.answer(caption, reply_markup=reply_markup)


async def _send_googleplay_instruction(message: Message) -> None:
    caption, image_path = GOOGLEPLAY_HAPP_STEP
    if image_path.exists():
        await message.answer_photo(FSInputFile(image_path), caption=caption, reply_markup=instruction_done_menu())
        return
    await message.answer(caption, reply_markup=instruction_done_menu())


def _find_plan(plans: list[Plan], code: str) -> Plan:
    for plan in plans:
        if plan.code == code:
            return plan
    raise RuntimeError(f"Unknown plan: {code}")


def _telegram_amount(plan: Plan, currency: str) -> int:
    zero_decimal = {"XTR", "JPY", "KRW"}
    return plan.price if currency.upper() in zero_decimal else plan.price * 100


def _is_admin(user_id: int | None, config: Config) -> bool:
    return user_id is not None and user_id in config.admin_ids


def _admin_stats_text(db: Database, config: Config) -> str:
    stats = db.stats()
    amounts = stats["payments_by_currency"]
    xtr_amount = amounts.get("XTR", 0)
    rub_amount = amounts.get("RUB", 0)
    return (
        "<b>Статистика ANDREVPN</b>\n\n"
        f"Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"Активных подписок: <b>{stats['active_users']}</b>\n"
        f"Пробных пользователей: <b>{stats['trial_users']}</b>\n"
        f"Просроченных подписок: <b>{stats['expired_users']}</b>\n\n"
        f"Оплат в этом месяце: <b>{stats['payments_count']}</b>\n"
        f"Stars за месяц: <b>{xtr_amount} XTR</b>\n"
        f"Рубли за месяц: <b>{_format_rub_kopecks(rub_amount)}</b>\n\n"
        f"Реферальных бонусов: <b>{stats['referral_rewards_count']}</b>\n"
        f"Начислено бонусных дней: <b>{stats['referral_reward_days']}</b>"
    )


def _parse_admin_add_request(text: str) -> tuple[int, int]:
    parts = text.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError("Expected telegram_id and days")
    telegram_id = int(parts[0])
    days = int(parts[1])
    if telegram_id <= 0 or days <= 0 or days > 3660:
        raise ValueError("Invalid telegram_id or days")
    return telegram_id, days


def _server_status_text() -> str:
    disk = shutil.disk_usage("/")
    ram = _read_memory_usage()
    load = _read_load_average()
    uptime = _read_uptime()
    bot_status = _systemd_status("andrevpn-bot")
    xui_status = _systemd_status("x-ui")

    disk_used = disk.total - disk.free
    return (
        "<b>Сервер ANDREVPN</b>\n\n"
        f"CPU load: <b>{load}</b>\n"
        f"RAM: <b>{_format_bytes(ram[0])} / {_format_bytes(ram[1])}</b> ({ram[2]}%)\n"
        f"Диск: <b>{_format_bytes(disk_used)} / {_format_bytes(disk.total)}</b> ({round(disk_used / disk.total * 100)}%)\n"
        f"Uptime: <b>{uptime}</b>\n\n"
        f"Бот: <b>{bot_status}</b>\n"
        f"3X-UI: <b>{xui_status}</b>"
    )


def _read_load_average() -> str:
    try:
        return " / ".join(f"{value:.2f}" for value in os.getloadavg())
    except (AttributeError, OSError):
        return "недоступно"


def _read_memory_usage() -> tuple[int, int, int]:
    try:
        values: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as file:
            for line in file:
                key, raw_value = line.split(":", 1)
                values[key] = int(raw_value.strip().split()[0]) * 1024
        total = values["MemTotal"]
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = total - available
        percent = round(used / total * 100) if total else 0
        return used, total, percent
    except (OSError, KeyError, ValueError):
        return 0, 0, 0


def _read_uptime() -> str:
    try:
        with open("/proc/uptime", encoding="utf-8") as file:
            seconds = int(float(file.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return "недоступно"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days} д. {hours} ч. {minutes} мин."
    return f"{hours} ч. {minutes} мин."


def _systemd_status(service: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "недоступно"
    return (result.stdout or result.stderr).strip() or "unknown"


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def _notify_user_about_admin_subscription(bot, user, days: int) -> None:
    try:
        await bot.send_message(
            user.telegram_id,
            (
                "<b>Подписка ANDREVPN активирована</b>\n\n"
                f"Доступ выдан на {days} дней.\n"
                f"Активна до: <b>{format_dt(user.subscription_until)}</b>\n\n"
                "Откройте раздел <b>Получить подключение</b>, чтобы скопировать ссылку."
            ),
            reply_markup=main_menu(False),
        )
    except Exception:
        pass


async def _notify_referral_grant(bot, grant: ReferralGrant, event_type: str) -> None:
    if event_type == "trial":
        text = (
            "<b>По твоей ссылке новый пользователь запустил пробный период!</b>\n\n"
            f"Мы начислили тебе +{grant.reward.reward_days} дня VPN."
        )
    else:
        text = (
            "<b>Твой приглашённый друг оплатил VPN!</b>\n\n"
            f"Мы начислили тебе +{grant.reward.reward_days} дней к подписке."
        )
    try:
        await bot.send_message(grant.referrer.telegram_id, text)
    except Exception:
        pass


async def _notify_support_message(message: Message, config: Config, user) -> None:
    username = f"@{user.username}" if user.username else "нет"
    name = user.first_name or "нет"
    header = (
        "<b>Новый вопрос в поддержку</b>\n\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Username: {username}\n"
        f"Имя: {name}"
    )
    for admin_id in config.admin_ids:
        try:
            await message.bot.send_message(admin_id, header)
            await message.bot.copy_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
        except Exception:
            pass


async def _notify_admins(bot, config: Config, text: str) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
