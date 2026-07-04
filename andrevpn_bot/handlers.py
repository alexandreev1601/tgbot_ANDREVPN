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
    instructions_back_menu,
    instructions_ios_menu,
    instructions_os_menu,
    main_menu,
    plans_menu,
    trial_menu,
)
from .texts import cabinet, connection_link_message, connection_text, format_dt, trial_success_text, trial_text, welcome
from .xui import XuiApi, XuiError


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


def build_router(config: Config, db: Database, xui: XuiApi) -> Router:
    router = Router()
    admin_add_waiting: set[int] = set()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        is_new_user = not db.user_exists(message.from_user.id)
        db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
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
            "<b>Android</b>\n\nИнструкция для Android будет добавлена позже.",
            instructions_back_menu(),
        )
        await callback.answer()

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
            "<b>Что делать если в App Store</b>\n\nИнструкция будет добавлена позже.",
            instructions_ios_menu(),
        )
        await callback.answer()

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
            "<b>Выберите срок подписки</b>",
            plans_menu(config.plans, config.payment_currency),
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

        updated_user = db.extend_subscription(user.telegram_id, plan.days)
        db.add_payment(
            telegram_id=user.telegram_id,
            plan_code=plan.code,
            amount=message.successful_payment.total_amount,
            currency=message.successful_payment.currency,
            provider_payment_charge_id=message.successful_payment.provider_payment_charge_id,
            telegram_payment_charge_id=message.successful_payment.telegram_payment_charge_id,
            raw_payload=json.dumps(message.successful_payment.model_dump(mode="json"), ensure_ascii=False),
        )

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


async def _send_happ_instruction(message: Message) -> None:
    for caption, image_path in HAPP_STEPS:
        if image_path.exists():
            await message.answer_photo(FSInputFile(image_path), caption=caption)
        else:
            await message.answer(caption)


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
    currency = config.payment_currency.upper()
    return (
        "<b>Статистика ANDREVPN</b>\n\n"
        f"Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"Активных подписок: <b>{stats['active_users']}</b>\n"
        f"Пробных пользователей: <b>{stats['trial_users']}</b>\n"
        f"Просроченных подписок: <b>{stats['expired_users']}</b>\n\n"
        f"Оплат в этом месяце: <b>{stats['payments_count']}</b>\n"
        f"Сумма за месяц: <b>{stats['payments_amount']} {currency}</b>"
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


async def _notify_admins(bot, config: Config, text: str) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
