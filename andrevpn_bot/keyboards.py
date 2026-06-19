from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import Plan


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Личный кабинет", callback_data="cabinet")],
        [InlineKeyboardButton(text="Оплатить / продлить", callback_data="plans")],
        [InlineKeyboardButton(text="Получить пробную версию", callback_data="trial")],
        [InlineKeyboardButton(text="Инструкция HAPP", callback_data="happ")],
        [InlineKeyboardButton(text="Получить подключение", callback_data="connection")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админ панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_menu(plans: list[Plan], currency: str) -> InlineKeyboardMarkup:
    currency_label = "XTR" if currency.upper() == "XTR" else "₽"
    rows = [
        [InlineKeyboardButton(text=f"{plan.title} - {plan.price} {currency_label}", callback_data=f"pay:{plan.code}")]
        for plan in plans
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
