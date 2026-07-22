from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, LabeledPrice, Message, PreCheckoutQuery

from .config import Config, Plan
from .db import ActiveSubscriptionError, Database, TrialAlreadyUsedError
from .keyboards import (
    BTN_ADMIN,
    BTN_CANCEL_SUPPORT,
    BTN_CONNECT,
    BTN_INSTRUCTIONS,
    BTN_PAY,
    BTN_PROFILE,
    BTN_REFERRALS,
    BTN_SUPPORT,
    COPY_TEXT_LIMIT,
    HAPP_DOWNLOAD_URL,
    MAIN_REPLY_BUTTONS,
    admin_back_menu,
    admin_grant_confirm_menu,
    admin_grant_days_menu,
    admin_menu,
    back_menu,
    connection_menu,
    home_actions_menu,
    inactive_connection_menu,
    instruction_step_menu,
    instructions_android_menu,
    instructions_ios_menu,
    instructions_os_menu,
    main_reply_keyboard,
    payment_method_menu,
    plans_menu,
    profile_menu,
    referrals_menu,
    sbp_payment_menu,
    sbp_plans_menu,
    success_menu,
    support_cancel_keyboard,
    support_categories_menu,
    support_hint_menu,
    trial_menu,
)
from .payments import PaidSubscriptionService
from .referrals import ReferralGrant, ReferralService
from .texts import (
    cabinet,
    connection_link,
    connection_text,
    format_date,
    format_dt,
    home_card,
    profile_card,
    trial_success_text,
    trial_text,
    welcome,
)
from .xui import XuiApi, XuiError
from .yookassa import YookassaError, YookassaPaymentService, YookassaVerificationError


WELCOME_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "welcome.png"
ASSETS_PATH = Path(__file__).resolve().parent.parent / "assets"
MAX_ADMIN_GRANT_DAYS = 3660

HAPP_STEPS = (
    ("Установите приложение Happ - Proxy Utility", ASSETS_PATH / "happ_step_3.jpg"),
    ('В боте откройте раздел "Подключить VPN" и скопируйте персональную ссылку', ASSETS_PATH / "happ_step_2.jpg"),
    ('Зайдите в Happ - Proxy Utility и нажмите "Из Буфера" -> Разрешить Вставку', ASSETS_PATH / "happ_step_1.jpg"),
)
ANDROID_HAPP_STEPS = (
    ("Установите приложение Happ - Proxy Utility", ASSETS_PATH / "android_happ_step_1.png"),
    *HAPP_STEPS[1:],
)
GOOGLEPLAY_HAPP_STEPS = (
    (
        "Google Play может удалить HAPP из Play Market, из-за этого нужно скачать приложение напрямую.\n\n"
        f'Перейдите по ссылке: <a href="{HAPP_DOWNLOAD_URL}">{HAPP_DOWNLOAD_URL}</a> '
        'и выберите под пунктом Android "Download APK". Начнется скачивание установочного файла. '
        "После скачивания установите его. HAPP должен появиться у вас на телефоне.",
        ASSETS_PATH / "googleplay_happ_apk.png",
    ),
)
APPSTORE_STEPS = (
    (
        "В данный момент Happ недоступен в Российском App Store. Но в зарубежном он есть. "
        "Чтобы у вас появились недоступные приложения, нужно поменять регион. "
        "Так же появятся приложения такие как ChatGPT, Google Gemini, Grok и т.д. "
        "Для этого перейдите в свой аккаунт App Store.",
        ASSETS_PATH / "appstore_step_1.jpg",
    ),
    ("Перейдите в управление аккаунтом.", ASSETS_PATH / "appstore_step_2.jpg"),
    ('Выберите пункт "Страна и регион", найдите и выберите "Соединенные штаты".', ASSETS_PATH / "appstore_step_3.jpg"),
    (
        "Введите эти данные. Эти данные сгенерированы и не существующие. "
        "Либо можно сгенерировать свои данные и ввести их.",
        ASSETS_PATH / "appstore_step_4.jpg",
    ),
    ("Готово! Сейчас перейдите в поиск приложений и у вас появится приложение HAPP, v2RayTun, AI приложения.", None),
)
INSTRUCTION_SETS = {
    "ios_happ": HAPP_STEPS,
    "android_happ": ANDROID_HAPP_STEPS,
    "ios_appstore": APPSTORE_STEPS,
    "android_googleplay": GOOGLEPLAY_HAPP_STEPS,
}


@dataclass
class AdminGrantState:
    step: str
    target_id: int | None = None
    days: int | None = None


def build_router(config: Config, db: Database, xui: XuiApi) -> Router:
    router = Router()
    referrals = ReferralService(db)
    paid_subscriptions = PaidSubscriptionService(db, referrals)
    yookassa = YookassaPaymentService(config, db) if config.yookassa_enabled else None
    admin_grants: dict[int, AdminGrantState] = {}
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
            await _notify_new_user(message, config)
        await message.answer(
            "Меню закреплено под полем ввода.",
            reply_markup=main_reply_keyboard(_is_admin(message.from_user.id, config)),
        )
        await _send_start_home(message, config, user)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "Выберите нужный раздел в меню под полем ввода. "
            "Команды тоже работают: /profile, /connect, /pay, /cancel.",
            reply_markup=main_reply_keyboard(_message_is_admin(message, config)),
        )

    @router.message(Command("cancel"))
    async def cancel_command(message: Message) -> None:
        if message.from_user is None:
            return
        admin_grants.pop(message.from_user.id, None)
        support_waiting.discard(message.from_user.id)
        await message.answer(
            "Текущий ввод отменен.",
            reply_markup=main_reply_keyboard(_is_admin(message.from_user.id, config)),
        )

    @router.message(Command("profile"))
    async def profile_command(message: Message) -> None:
        if message.from_user is None:
            return
        user = db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await message.answer(
            profile_card(user, _traffic_summary(xui, user)),
            reply_markup=profile_menu(is_active=user.is_active, trial_available=_trial_available(user)),
        )

    @router.message(Command("connect"))
    async def connect_command(message: Message) -> None:
        if message.from_user is None:
            return
        user = db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await _send_connection_from_message(message, user, config, db, xui)

    @router.message(Command("pay"))
    async def pay_command(message: Message) -> None:
        if message.from_user is None:
            return
        db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await message.answer("<b>Оплата</b>\n\nВыберите способ оплаты.", reply_markup=payment_method_menu(config.yookassa_enabled))

    @router.message(F.text == BTN_PROFILE)
    async def profile_button(message: Message) -> None:
        await profile_command(message)

    @router.message(F.text == BTN_PAY)
    async def pay_button(message: Message) -> None:
        await pay_command(message)

    @router.message(F.text == BTN_CONNECT)
    async def connect_button(message: Message) -> None:
        await connect_command(message)

    @router.message(F.text == BTN_INSTRUCTIONS)
    async def instructions_button(message: Message) -> None:
        if message.from_user is None:
            return
        db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await message.answer("📖 <b>Инструкция по подключению</b>\n\nВыберите операционную систему.", reply_markup=instructions_os_menu())

    @router.message(F.text == BTN_REFERRALS)
    async def referrals_button(message: Message) -> None:
        if message.from_user is None:
            return
        user = referrals.ensure_referral_code(db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name))
        await _send_referrals_from_message(message, referrals, user)

    @router.message(F.text == BTN_SUPPORT)
    async def support_button(message: Message) -> None:
        if message.from_user is None:
            return
        db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await message.answer("🆘 <b>Поддержка</b>\n\nВыберите тему вопроса.", reply_markup=support_categories_menu())

    @router.message(F.text == BTN_ADMIN)
    async def admin_button(message: Message) -> None:
        if message.from_user is None or not _is_admin(message.from_user.id, config):
            await message.answer("Нет доступа.")
            return
        await message.answer("⚙️ <b>Админ-панель</b>\n\nВыберите действие.", reply_markup=admin_menu())

    @router.message(F.text == BTN_CANCEL_SUPPORT)
    async def cancel_support_button(message: Message) -> None:
        if message.from_user is None:
            return
        support_waiting.discard(message.from_user.id)
        await message.answer(
            "Обращение отменено.",
            reply_markup=main_reply_keyboard(_is_admin(message.from_user.id, config)),
        )

    @router.callback_query(F.data == "noop")
    async def noop(callback: CallbackQuery) -> None:
        await callback.answer()

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        restore_reply_keyboard = callback.from_user.id in support_waiting
        admin_grants.pop(callback.from_user.id, None)
        support_waiting.discard(callback.from_user.id)
        user = _touch_user(callback, db)
        await _show_section(callback, home_card(user, config), home_actions_menu(is_active=user.is_active, trial_available=_trial_available(user)))
        if restore_reply_keyboard and callback.message:
            await callback.message.answer(
                "Основная клавиатура восстановлена.",
                reply_markup=main_reply_keyboard(_is_admin(callback.from_user.id, config)),
            )

    @router.callback_query(F.data == "admin")
    async def admin_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        admin_grants.pop(callback.from_user.id, None)
        await callback.answer()
        await _show_section(callback, "⚙️ <b>Админ-панель</b>\n\nВыберите действие.", admin_menu())

    @router.callback_query(F.data == "admin:stats")
    async def admin_stats_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        await callback.answer()
        await _show_section(callback, _admin_stats_text(db, config), admin_back_menu())

    @router.callback_query(F.data == "admin:add")
    async def admin_add_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        admin_grants[callback.from_user.id] = AdminGrantState(step="await_id")
        await callback.answer()
        await _show_section(
            callback,
            "➕ <b>Выдать подписку</b>\n\nОтправьте Telegram ID пользователя одним сообщением.",
            admin_back_menu(),
        )

    @router.callback_query(F.data.startswith("admin:add:days:"))
    async def admin_add_days_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        state = admin_grants.get(callback.from_user.id)
        if state is None or state.target_id is None:
            await callback.answer("Сначала введите Telegram ID.", show_alert=True)
            return
        days = int(callback.data.rsplit(":", 1)[1])
        state.days = days
        state.step = "confirm"
        await callback.answer()
        await _show_admin_grant_confirmation(callback, db, state)

    @router.callback_query(F.data == "admin:add:custom")
    async def admin_add_custom_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        state = admin_grants.get(callback.from_user.id)
        if state is None or state.target_id is None:
            await callback.answer("Сначала введите Telegram ID.", show_alert=True)
            return
        state.step = "await_days"
        await callback.answer()
        await _show_section(
            callback,
            f"ID: <code>{state.target_id}</code>\n\nОтправьте срок подписки в днях числом.",
            admin_back_menu(),
        )

    @router.callback_query(F.data == "admin:add:cancel")
    async def admin_add_cancel_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        admin_grants.pop(callback.from_user.id, None)
        await callback.answer("Отменено.")
        await _show_section(callback, "⚙️ <b>Админ-панель</b>\n\nВыберите действие.", admin_menu())

    @router.callback_query(F.data == "admin:add:confirm")
    async def admin_add_confirm_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        state = admin_grants.get(callback.from_user.id)
        if state is None or state.target_id is None or state.days is None:
            await callback.answer("Нет данных для выдачи.", show_alert=True)
            return

        user = db.get_or_create_user(state.target_id)
        updated_user = db.extend_subscription(user.telegram_id, state.days)
        try:
            await xui.provision_user(db, updated_user)
            updated_user = db.get_user(user.telegram_id)
        except XuiError as exc:
            await callback.answer("Подписка продлена, но XUI не обновился.", show_alert=True)
            await _show_section(
                callback,
                f"Подписка продлена, но подключение в 3X-UI не создалось:\n<code>{escape(str(exc))}</code>",
                admin_back_menu(),
            )
            return

        admin_grants.pop(callback.from_user.id, None)
        await callback.answer("Подписка выдана.")
        await _show_section(
            callback,
            (
                "✅ <b>Подписка выдана</b>\n\n"
                f"ID: <code>{updated_user.telegram_id}</code>\n"
                f"Срок: {state.days} дней\n"
                f"Активна до: <b>{format_date(updated_user.subscription_until)}</b>"
            ),
            admin_back_menu(),
        )
        await _notify_user_about_admin_subscription(callback.message.bot, updated_user, state.days)
        await _notify_admins(
            callback.message.bot,
            config,
            f"<b>Ручная выдача подписки</b>\nID: <code>{updated_user.telegram_id}</code>\nСрок: {state.days} дней",
        )

    @router.callback_query(F.data == "admin:server")
    async def admin_server_handler(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id, config):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        await callback.answer()
        await _show_section(callback, _server_status_text(), admin_back_menu())

    @router.callback_query(F.data.in_({"profile", "cabinet"}))
    async def profile_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        await callback.answer()
        await _show_section(
            callback,
            profile_card(user, _traffic_summary(xui, user)),
            profile_menu(is_active=user.is_active, trial_available=_trial_available(user)),
        )

    @router.callback_query(F.data == "referrals")
    async def referrals_handler(callback: CallbackQuery) -> None:
        user = referrals.ensure_referral_code(_touch_user(callback, db))
        await callback.answer()
        if callback.message:
            await _send_referrals_from_message(callback.message, referrals, user, callback=callback)

    @router.callback_query(F.data == "support")
    async def support_handler(callback: CallbackQuery) -> None:
        restore_reply_keyboard = callback.from_user.id in support_waiting
        support_waiting.discard(callback.from_user.id)
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(callback, "🆘 <b>Поддержка</b>\n\nВыберите тему вопроса.", support_categories_menu())
        if restore_reply_keyboard and callback.message:
            await callback.message.answer(
                "Основная клавиатура восстановлена.",
                reply_markup=main_reply_keyboard(_is_admin(callback.from_user.id, config)),
            )

    @router.callback_query(F.data.startswith("support:"))
    async def support_category_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        action = callback.data.split(":", 1)[1]
        await callback.answer()
        if action == "operator":
            support_waiting.add(user.telegram_id)
            await _show_section(
                callback,
                (
                    "👨‍💻 <b>Оператор</b>\n\n"
                    "Отправьте следующим сообщением вопрос, фото или скриншот. "
                    "Мы передадим обращение администратору."
                ),
                back_menu("support"),
            )
            if callback.message:
                await callback.message.answer("Ожидаю сообщение для поддержки.", reply_markup=support_cancel_keyboard())
            return
        if action == "done":
            await _show_section(callback, "Отлично. Главное меню доступно ниже.", back_menu("home"))
            return
        await _show_section(callback, _support_hint_text(action), support_hint_menu())

    @router.callback_query(F.data == "instructions")
    async def instructions_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(callback, "📖 <b>Инструкция по подключению</b>\n\nВыберите операционную систему.", instructions_os_menu())

    @router.callback_query(F.data == "instructions:android")
    async def instructions_android_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(callback, "🤖 <b>Android</b>\n\nВыберите нужный раздел.", instructions_android_menu())

    @router.callback_query(F.data == "instructions:ios")
    async def instructions_ios_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(callback, "🍎 <b>iPhone / iPad</b>\n\nВыберите нужный раздел.", instructions_ios_menu())

    @router.callback_query(F.data.startswith("instr:"))
    async def instruction_step_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        await callback.answer()
        _, key, raw_index = callback.data.split(":", 2)
        steps = INSTRUCTION_SETS.get(key)
        if not steps:
            await _show_section(callback, "Инструкция не найдена.", instructions_os_menu())
            return
        index = max(0, min(int(raw_index), len(steps) - 1))
        link = connection_link(user, config) if key in {"ios_happ", "android_happ"} and index == 1 else None
        await _show_instruction_step(callback, key, index, steps, link)

    @router.callback_query(F.data == "trial")
    async def trial_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        keyboard = trial_menu() if _trial_available(user) else back_menu("home")
        await callback.answer()
        await _show_section(callback, trial_text(user), keyboard)

    @router.callback_query(F.data == "trial:activate")
    async def trial_activate_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        try:
            updated_user = db.activate_trial(user.telegram_id, days=3)
        except TrialAlreadyUsedError:
            await _show_section(callback, trial_text(db.get_user(user.telegram_id)), back_menu("home"))
            await callback.answer("Пробный период уже был использован.", show_alert=True)
            return
        except ActiveSubscriptionError:
            await _show_section(callback, trial_text(db.get_user(user.telegram_id)), back_menu("home"))
            await callback.answer("У вас уже есть активная подписка.", show_alert=True)
            return

        try:
            await xui.provision_user(db, updated_user)
            updated_user = db.get_user(user.telegram_id)
        except XuiError as exc:
            await callback.answer("Пробная подписка активирована, но подключение создаётся вручную.", show_alert=True)
            await _notify_admins(callback.message.bot, config, f"Trial user {user.telegram_id}, but 3X-UI failed: {exc}")
            return

        await callback.answer("Пробная подписка активирована.")
        await _show_section(callback, trial_success_text(updated_user), success_menu())
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
        await callback.answer()
        await _show_connection_from_callback(callback, user, config, db, xui)

    @router.callback_query(F.data == "plans")
    async def plans_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(callback, "<b>Оплата</b>\n\nВыберите способ оплаты.", payment_method_menu(config.yookassa_enabled))

    @router.callback_query(F.data == "plans:stars")
    async def stars_plans_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.answer()
        await _show_section(
            callback,
            "<b>Telegram Stars</b>\n\nВыберите срок подписки.",
            plans_menu(config.plans, config.payment_currency, back_callback="plans"),
        )

    @router.callback_query(F.data == "plans:sbp")
    async def sbp_plans_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        if yookassa is None:
            await callback.answer()
            await _show_section(callback, "<b>СБП через ЮKassa</b>\n\nОплата через СБП временно недоступна.", back_menu("plans"))
            return
        await callback.answer()
        await _show_section(callback, "<b>СБП через ЮKassa</b>\n\nВыберите срок подписки.", sbp_plans_menu(config.sbp_plans))

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
            await callback.answer("Платёж не создан.", show_alert=True)
            await _show_section(callback, "<b>СБП через ЮKassa</b>\n\nНе удалось создать платёж. Попробуйте ещё раз чуть позже.", sbp_plans_menu(config.sbp_plans))
            await _notify_admins(callback.message.bot, config, f"YooKassa create payment error for {user.telegram_id}: {exc}")
            return
        if not order.confirmation_url:
            await callback.answer("ЮKassa не вернула ссылку оплаты.", show_alert=True)
            return

        await callback.answer()
        await _show_section(callback, _sbp_order_text(order, config), sbp_payment_menu(order.id, order.confirmation_url))

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
            await callback.answer("Неизвестный платёж.", show_alert=True)
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
            await callback.answer()
            await _show_section(callback, "<b>Платёж отменён</b>\n\nСоздайте новый платёж и попробуйте снова.", sbp_plans_menu(config.sbp_plans))
            return
        if result.status != "succeeded" or result.finalization is None:
            await callback.answer("Платёж пока не подтверждён.", show_alert=True)
            return

        if not result.finalization.already_processed:
            await _after_successful_external_payment(callback.message.bot, config, db, xui, yookassa, result.finalization)
        await callback.answer()
        await _show_section(
            callback,
            "✅ <b>Оплата подтверждена</b>\n\n"
            "Подписка ANDREVPN продлена.\n\n"
            f"Активна до: <b>{format_date(result.finalization.user.subscription_until)}</b>",
            success_menu(),
        )

    @router.callback_query(F.data.startswith("pay:"))
    async def pay_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        plan = _find_plan(config.plans, callback.data.split(":", 1)[1])

        is_stars_payment = config.payment_currency.upper() == "XTR"
        if not is_stars_payment and not config.payment_provider_token:
            await callback.answer()
            await _show_section(
                callback,
                "<b>Оплата пока не подключена</b>\n\n"
                "Тариф выбран, но платёжный токен ещё не указан в настройках бота. "
                "Напишите администратору для ручного продления.",
                back_menu("plans:stars"),
            )
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
                reply_markup=main_reply_keyboard(_is_admin(user.telegram_id, config)),
            )
            return

        if result.referral_grant:
            await _notify_referral_grant(message.bot, result.referral_grant, "payment")

        await message.answer(
            "✅ <b>Оплата прошла успешно</b>\n\n"
            f"Подписка ANDREVPN продлена до: <b>{format_date(updated_user.subscription_until)}</b>",
            reply_markup=success_menu(),
        )
        await _notify_admins(
            message.bot,
            config,
            (
                "<b>Продление подписки</b>\n"
                f"ID: <code>{user.telegram_id}</code>\n"
                f"Тариф: {escape(plan.title)}\n"
                f"Сумма: {message.successful_payment.total_amount} {message.successful_payment.currency}\n"
                f"Активна до: <b>{format_dt(updated_user.subscription_until)}</b>"
            ),
        )

    @router.message(
        lambda message: message.from_user is not None
        and message.from_user.id in support_waiting
        and (message.text is None or message.text not in MAIN_REPLY_BUTTONS | {BTN_CANCEL_SUPPORT})
    )
    async def support_message_handler(message: Message) -> None:
        if message.from_user is None:
            return

        user = db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await _notify_support_message(message, config, user)
        await message.answer(
            (
                "Сообщение отправлено в поддержку.\n\n"
                "Можно отправить еще один скриншот или дополнительный текст. "
                "Чтобы выйти, нажмите кнопку отмены."
            ),
            reply_markup=support_cancel_keyboard(),
        )

    @router.message(F.text)
    async def admin_text_handler(message: Message) -> None:
        if message.from_user is None:
            return

        state = admin_grants.get(message.from_user.id)
        if state is None:
            await message.answer(
                "Я не понял сообщение. Пожалуйста, выберите нужный раздел в меню под полем ввода.",
                reply_markup=main_reply_keyboard(_is_admin(message.from_user.id, config)),
            )
            return

        if not _is_admin(message.from_user.id, config):
            admin_grants.pop(message.from_user.id, None)
            await message.answer("Нет доступа.")
            return

        if state.step == "await_id":
            try:
                target_id = _parse_positive_int(message.text or "", max_value=10**12)
            except ValueError:
                await message.answer("Отправьте только Telegram ID пользователя числом.", reply_markup=admin_back_menu())
                return
            state.target_id = target_id
            state.step = "await_days_choice"
            await message.answer(
                f"ID: <code>{target_id}</code>\n\nВыберите срок подписки.",
                reply_markup=admin_grant_days_menu(),
            )
            return

        if state.step == "await_days":
            try:
                days = _parse_positive_int(message.text or "", max_value=MAX_ADMIN_GRANT_DAYS)
            except ValueError:
                await message.answer(f"Отправьте целое число дней от 1 до {MAX_ADMIN_GRANT_DAYS}.", reply_markup=admin_back_menu())
                return
            state.days = days
            state.step = "confirm"
            await _show_admin_grant_confirmation_message(message, db, state)
            return

        await message.answer("Выберите действие кнопками ниже.", reply_markup=admin_back_menu())

    return router


def _touch_user(callback: CallbackQuery, db: Database):
    if callback.from_user is None:
        raise RuntimeError("Callback without Telegram user")
    return db.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)


def _message_is_admin(message: Message, config: Config) -> bool:
    return message.from_user is not None and _is_admin(message.from_user.id, config)


def _start_argument(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else None


def _trial_available(user) -> bool:
    return user.trial_used_at is None and not user.is_active


def _traffic_summary(xui: XuiApi, user):
    try:
        return xui.traffic_summary(user)
    except Exception:
        return None


async def _notify_new_user(message: Message, config: Config) -> None:
    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "нет"
    await _notify_admins(
        message.bot,
        config,
        f"<b>Новый клиент</b>\nID: <code>{message.from_user.id}</code>\nUsername: {username}",
    )


async def _send_start_home(message: Message, config: Config, user) -> None:
    text = welcome(config) + "\n\n" + home_card(user, config)
    keyboard = home_actions_menu(is_active=user.is_active, trial_available=_trial_available(user))
    if WELCOME_IMAGE_PATH.exists():
        await message.answer_photo(FSInputFile(WELCOME_IMAGE_PATH), caption=text, reply_markup=keyboard)
        return
    await message.answer(text, reply_markup=keyboard)


async def _show_connection_from_callback(callback: CallbackQuery, user, config: Config, db: Database, xui: XuiApi) -> None:
    if user.is_active:
        try:
            await xui.provision_user(db, user)
            user = db.get_user(user.telegram_id)
        except XuiError as exc:
            await callback.answer("Не удалось создать подключение, администратор уже получил ошибку.", show_alert=True)
            await _notify_admins(callback.message.bot, config, f"3X-UI error for {user.telegram_id}: {exc}")
            return

    link = connection_link(user, config)
    if user.is_active:
        await _show_section(callback, connection_text(user, config), connection_menu(link, can_copy=True))
        return
    await _show_section(callback, connection_text(user, config), inactive_connection_menu(trial_available=_trial_available(user)))


async def _send_connection_from_message(message: Message, user, config: Config, db: Database, xui: XuiApi) -> None:
    if user.is_active:
        try:
            await xui.provision_user(db, user)
            user = db.get_user(user.telegram_id)
        except XuiError as exc:
            await message.answer("Не удалось создать подключение, администратор уже получил ошибку.")
            await _notify_admins(message.bot, config, f"3X-UI error for {user.telegram_id}: {exc}")
            return

    link = connection_link(user, config)
    keyboard = connection_menu(link, can_copy=True) if user.is_active else inactive_connection_menu(trial_available=_trial_available(user))
    await message.answer(connection_text(user, config), reply_markup=keyboard)


async def _send_referrals_from_message(message: Message, referrals: ReferralService, user, *, callback: CallbackQuery | None = None) -> None:
    bot_info = await message.bot.get_me()
    if not bot_info.username:
        if callback:
            await callback.answer("Не удалось получить имя бота.", show_alert=True)
        else:
            await message.answer("Не удалось получить имя бота.")
        return
    link = referrals.referral_link(user, bot_info.username)
    text = _referral_program_text(user, link, referrals.stats(user))
    if callback:
        await _show_section(callback, text, referrals_menu(link))
        return
    await message.answer(text, reply_markup=referrals_menu(link))


def _referral_program_text(user, referral_link: str, stats: dict[str, int]) -> str:
    referrer = f"<code>{user.referred_by}</code>" if user.referred_by else "нет"
    return (
        "🎁 <b>Пригласить друга</b>\n\n"
        "Бонусы за приглашения:\n"
        "Пробный период друга - <b>+3 дня</b>\n"
        "Оплата 1 месяца - <b>+7 дней</b>\n"
        "Оплата 2 месяцев - <b>+14 дней</b>\n"
        "Оплата 3 месяцев - <b>+21 день</b>\n\n"
        f"Ваша ссылка:\n<code>{escape(referral_link)}</code>\n\n"
        f"Приглашено: <b>{stats['invited_users']}</b>\n"
        f"Начислено дней: <b>{stats['reward_days']}</b>\n"
        f"Вас пригласил: {referrer}"
    )


def _sbp_order_text(order, config: Config) -> str:
    try:
        title = _find_plan(config.sbp_plans, order.plan_code).title
    except RuntimeError:
        title = order.plan_code
    return (
        "<b>СБП через ЮKassa</b>\n\n"
        f"Тариф: <b>{escape(title)}</b>\n"
        f"Сумма: <b>{_format_rub_kopecks(order.amount_kopecks)}</b>\n\n"
        "Нажмите <b>Перейти к оплате</b>. После оплаты вернитесь в Telegram "
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
            "✅ <b>Оплата через СБП прошла успешно</b>\n\n"
            f"Подписка ANDREVPN продлена до: <b>{format_date(updated_user.subscription_until)}</b>",
            reply_markup=success_menu(),
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
            f"Тариф: {escape(finalization.order.plan_code)}\n"
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
        await _safe_edit_reply_markup(callback.message, None)
        await callback.message.answer(text, reply_markup=reply_markup)
        return
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=reply_markup)


async def _safe_edit_reply_markup(message: Message, reply_markup) -> None:
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest:
        pass


async def _show_instruction_step(callback: CallbackQuery, key: str, index: int, steps, link: str | None) -> None:
    if callback.message is None:
        return
    caption, image_path = steps[index]
    numbered_caption = f"{index + 1}. {caption}" if len(steps) > 1 else caption
    keyboard = instruction_step_menu(key=key, index=index, total=len(steps), link=link)

    if image_path and image_path.exists():
        media = InputMediaPhoto(media=FSInputFile(image_path), caption=numbered_caption)
        if callback.message.photo:
            try:
                await callback.message.edit_media(media=media, reply_markup=keyboard)
                return
            except TelegramBadRequest:
                pass
        await _replace_with_photo(callback.message, image_path, numbered_caption, keyboard)
        return

    if callback.message.photo:
        await _replace_with_text(callback.message, numbered_caption, keyboard)
        return
    try:
        await callback.message.edit_text(numbered_caption, reply_markup=keyboard)
    except TelegramBadRequest:
        await callback.message.answer(numbered_caption, reply_markup=keyboard)


async def _replace_with_photo(message: Message, image_path: Path, caption: str, reply_markup) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        await _safe_edit_reply_markup(message, None)
    await message.answer_photo(FSInputFile(image_path), caption=caption, reply_markup=reply_markup)


async def _replace_with_text(message: Message, text: str, reply_markup) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        await _safe_edit_reply_markup(message, None)
    await message.answer(text, reply_markup=reply_markup)


async def _show_admin_grant_confirmation(callback: CallbackQuery, db: Database, state: AdminGrantState) -> None:
    text = _admin_grant_confirmation_text(db, state)
    await _show_section(callback, text, admin_grant_confirm_menu())


async def _show_admin_grant_confirmation_message(message: Message, db: Database, state: AdminGrantState) -> None:
    await message.answer(_admin_grant_confirmation_text(db, state), reply_markup=admin_grant_confirm_menu())


def _admin_grant_confirmation_text(db: Database, state: AdminGrantState) -> str:
    if state.target_id is None or state.days is None:
        return "Недостаточно данных для подтверждения."
    try:
        user = db.get_user(state.target_id)
        base = user.subscription_until if user.subscription_until and user.subscription_until > datetime.now(UTC) else datetime.now(UTC)
    except LookupError:
        base = datetime.now(UTC)
    until = base + timedelta(days=state.days)
    return (
        "➕ <b>Подтвердите выдачу подписки</b>\n\n"
        f"ID: <code>{state.target_id}</code>\n"
        f"Срок: <b>{state.days} дней</b>\n"
        f"Будет активна до: <b>{format_date(until)}</b>"
    )


def _support_hint_text(action: str) -> str:
    hints = {
        "payment": (
            "💳 <b>Проблема с оплатой</b>\n\n"
            "Если платили через СБП, вернитесь в экран оплаты и нажмите <b>Проверить оплату</b>. "
            "Если подписка не продлилась, напишите оператору и приложите скриншот оплаты."
        ),
        "vpn": (
            "🔗 <b>Не подключается VPN</b>\n\n"
            "Проверьте, что подписка активна, обновите подписку в HAPP через вашу персональную ссылку "
            "и попробуйте другой доступный профиль."
        ),
        "speed": (
            "🐢 <b>Низкая скорость</b>\n\n"
            "Обновите подписку в HAPP и выберите другой доступный профиль ANDREVPN. "
            "Если не помогло, напишите оператору."
        ),
        "happ": (
            "📱 <b>Проблема с HAPP</b>\n\n"
            "Откройте раздел <b>Инструкция</b>, выберите вашу ОС и проверьте шаг подключения через «Из буфера»."
        ),
    }
    return hints.get(action, "Опишите вопрос оператору.")


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
        "📊 <b>Статистика ANDREVPN</b>\n\n"
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


def _parse_positive_int(text: str, *, max_value: int) -> int:
    value = int(text.strip())
    if value <= 0 or value > max_value:
        raise ValueError("out of range")
    return value


def _server_status_text() -> str:
    disk = shutil.disk_usage("/")
    ram = _read_memory_usage()
    load = _read_load_average()
    uptime = _read_uptime()
    bot_status = _systemd_status("andrevpn-bot")
    xui_status = _systemd_status("x-ui")

    disk_used = disk.total - disk.free
    return (
        "🖥 <b>Сервер ANDREVPN</b>\n\n"
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
                "Откройте раздел <b>Подключить VPN</b>, чтобы скопировать ссылку."
            ),
            reply_markup=success_menu(),
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
        f"Username: {escape(username)}\n"
        f"Имя: {escape(name)}"
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
