from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .config import Config, Plan
from .db import Database
from .keyboards import back_menu, main_menu, plans_menu
from .texts import cabinet, connection_text, happ_instruction, welcome
from .xui import XuiApi, XuiError


def build_router(config: Config, db: Database, xui: XuiApi) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        await message.answer(welcome(config), reply_markup=main_menu())

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.message.edit_text(welcome(config), reply_markup=main_menu())
        await callback.answer()

    @router.callback_query(F.data == "cabinet")
    async def cabinet_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        await callback.message.edit_text(cabinet(user), reply_markup=back_menu())
        await callback.answer()

    @router.callback_query(F.data == "happ")
    async def happ_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.message.edit_text(happ_instruction(config), reply_markup=back_menu())
        await callback.answer()

    @router.callback_query(F.data == "connection")
    async def connection_handler(callback: CallbackQuery) -> None:
        user = _touch_user(callback, db)
        if user.is_active and not user.xui_sub_id:
            try:
                await xui.provision_user(db, user)
                user = db.get_user(user.telegram_id)
            except XuiError as exc:
                await callback.answer("Не удалось создать подключение, администратор уже получил ошибку.", show_alert=True)
                await _notify_admins(callback.message.bot, config, f"3X-UI error for {user.telegram_id}: {exc}")
                return

        await callback.message.edit_text(connection_text(user, config), reply_markup=back_menu())
        await callback.answer()

    @router.callback_query(F.data == "plans")
    async def plans_handler(callback: CallbackQuery) -> None:
        _touch_user(callback, db)
        await callback.message.edit_text(
            "<b>Выберите срок подписки</b>",
            reply_markup=plans_menu(config.plans, config.payment_currency),
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
            await callback.message.edit_text(text, reply_markup=back_menu())
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
                reply_markup=main_menu(),
            )
            return

        await message.answer(
            "Оплата прошла успешно. Подписка ANDREVPN продлена.\n\n" + cabinet(updated_user),
            reply_markup=main_menu(),
        )

    return router


def _touch_user(callback: CallbackQuery, db: Database):
    if callback.from_user is None:
        raise RuntimeError("Callback without Telegram user")
    return db.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)


def _find_plan(plans: list[Plan], code: str) -> Plan:
    for plan in plans:
        if plan.code == code:
            return plan
    raise RuntimeError(f"Unknown plan: {code}")


def _telegram_amount(plan: Plan, currency: str) -> int:
    zero_decimal = {"XTR", "JPY", "KRW"}
    return plan.price if currency.upper() in zero_decimal else plan.price * 100


async def _notify_admins(bot, config: Config, text: str) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
