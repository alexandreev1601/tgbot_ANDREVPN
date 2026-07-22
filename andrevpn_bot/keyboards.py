from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import Plan


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Личный кабинет", callback_data="cabinet")],
        [InlineKeyboardButton(text="Оплатить / продлить", callback_data="plans")],
        [InlineKeyboardButton(text="Получить пробную версию", callback_data="trial")],
        [InlineKeyboardButton(text="Инструкция по подключению", callback_data="instructions")],
        [InlineKeyboardButton(text="Получить подключение", callback_data="connection")],
        [InlineKeyboardButton(text="Реферальная программа", callback_data="referrals")],
        [InlineKeyboardButton(text="Вопросы и Поддержка", callback_data="support")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админ панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_menu(plans: list[Plan], currency: str, back_callback: str = "home") -> InlineKeyboardMarkup:
    currency_label = "XTR" if currency.upper() == "XTR" else "₽"
    rows = [
        [InlineKeyboardButton(text=f"{plan.title} - {plan.price} {currency_label}", callback_data=f"pay:{plan.code}")]
        for plan in plans
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_menu(yookassa_enabled: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="TG звездами (автоматически)", callback_data="plans:stars")]]
    if yookassa_enabled:
        rows.append([InlineKeyboardButton(text="СБП через ЮKassa (автоматически)", callback_data="plans:sbp")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sbp_plans_menu(plans: list[Plan]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{plan.title} - {plan.price} рублей", callback_data=f"sbp:create:{plan.code}")]
        for plan in plans
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sbp_payment_menu(order_id: int, confirmation_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить через СБП", url=confirmation_url)],
            [InlineKeyboardButton(text="Проверить оплату", callback_data=f"sbp:check:{order_id}")],
            [InlineKeyboardButton(text="Назад к тарифам", callback_data="plans:sbp")],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="home")]]
    )


def trial_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Получить пробный период", callback_data="trial:activate")],
            [InlineKeyboardButton(text="Назад", callback_data="home")],
        ]
    )


def instructions_os_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Android", callback_data="instructions:android")],
            [InlineKeyboardButton(text="IOS", callback_data="instructions:ios")],
            [InlineKeyboardButton(text="Назад", callback_data="home")],
        ]
    )


def instructions_ios_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Как подключить подписку к HAPP", callback_data="instructions:ios:happ")],
            [InlineKeyboardButton(text="Что делать если в App Store нет HAPP", callback_data="instructions:ios:appstore")],
            [InlineKeyboardButton(text="Назад", callback_data="instructions")],
        ]
    )


def instructions_android_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Как подключить подписку к HAPP", callback_data="instructions:android:happ")],
            [InlineKeyboardButton(text="Что делать если в Google Play нет HAPP", callback_data="instructions:android:googleplay")],
            [InlineKeyboardButton(text="Назад", callback_data="instructions")],
        ]
    )


def instructions_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад к выбору ОС", callback_data="instructions")],
            [InlineKeyboardButton(text="Главная", callback_data="home")],
        ]
    )


def instruction_done_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Главное меню", callback_data="home")],
        ]
    )


def support_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Главное меню", callback_data="home")],
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="Добавить подписку по ID", callback_data="admin:add")],
            [InlineKeyboardButton(text="Сервер", callback_data="admin:server")],
            [InlineKeyboardButton(text="Назад", callback_data="home")],
        ]
    )


def admin_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад в админ панель", callback_data="admin")],
            [InlineKeyboardButton(text="Главная", callback_data="home")],
        ]
    )
