from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import Plan


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Личный кабинет", callback_data="cabinet")],
            [InlineKeyboardButton(text="Оплатить / продлить", callback_data="plans")],
            [InlineKeyboardButton(text="Инструкция HAPP", callback_data="happ")],
            [InlineKeyboardButton(text="Получить подключение", callback_data="connection")],
        ]
    )


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
