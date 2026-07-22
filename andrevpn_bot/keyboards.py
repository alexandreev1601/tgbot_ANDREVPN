from __future__ import annotations

from urllib.parse import quote

from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .config import Plan


BTN_PROFILE = "👤 Моя подписка"
BTN_PAY = "💳 Оплатить"
BTN_CONNECT = "🔗 Подключить VPN"
BTN_INSTRUCTIONS = "📖 Инструкция"
BTN_REFERRALS = "🎁 Пригласить друга"
BTN_SUPPORT = "🆘 Поддержка"
BTN_ADMIN = "⚙️ Админ-панель"
BTN_CANCEL_SUPPORT = "❌ Отменить обращение"

MAIN_REPLY_BUTTONS = {
    BTN_PROFILE,
    BTN_PAY,
    BTN_CONNECT,
    BTN_INSTRUCTIONS,
    BTN_REFERRALS,
    BTN_SUPPORT,
    BTN_ADMIN,
}

COPY_TEXT_LIMIT = 256
HAPP_DOWNLOAD_URL = "https://www.happ.su/main/ru"


def main_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_PAY)],
        [KeyboardButton(text=BTN_CONNECT), KeyboardButton(text=BTN_INSTRUCTIONS)],
        [KeyboardButton(text=BTN_REFERRALS), KeyboardButton(text=BTN_SUPPORT)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел в меню",
    )


def support_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL_SUPPORT)]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Опишите вопрос или отмените обращение",
    )


def home_actions_menu(*, is_active: bool, trial_available: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_active:
        rows.append([InlineKeyboardButton(text="🔗 Подключить VPN", callback_data="connection")])
        rows.append([InlineKeyboardButton(text="💳 Продлить", callback_data="plans")])
        rows.append([InlineKeyboardButton(text="👤 Подробнее", callback_data="profile")])
    else:
        if trial_available:
            rows.append([InlineKeyboardButton(text="🎁 Попробовать 3 дня", callback_data="trial")])
        rows.append([InlineKeyboardButton(text="💳 Выбрать тариф", callback_data="plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_menu(*, is_active: bool, trial_available: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_active:
        rows.extend(
            [
                [InlineKeyboardButton(text="🔗 Подключить VPN", callback_data="connection")],
                [InlineKeyboardButton(text="💳 Продлить", callback_data="plans")],
                [InlineKeyboardButton(text="📖 Инструкция", callback_data="instructions")],
            ]
        )
    else:
        if trial_available:
            rows.append([InlineKeyboardButton(text="🎁 Попробовать 3 дня", callback_data="trial")])
        rows.append([InlineKeyboardButton(text="💳 Купить подписку", callback_data="plans")])
    rows.append(_back_home_row("home"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def connection_menu(link: str | None, *, can_copy: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if link and can_copy and len(link) <= COPY_TEXT_LIMIT:
        rows.append([InlineKeyboardButton(text="📋 Скопировать ссылку", copy_text=CopyTextButton(text=link))])
    rows.extend(
        [
            [InlineKeyboardButton(text="📲 Скачать HAPP", url=HAPP_DOWNLOAD_URL)],
            [InlineKeyboardButton(text="📖 Как подключить", callback_data="instructions")],
            _back_home_row("home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inactive_connection_menu(*, trial_available: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if trial_available:
        rows.append([InlineKeyboardButton(text="🎁 Попробовать 3 дня", callback_data="trial")])
    rows.append([InlineKeyboardButton(text="💳 Купить подписку", callback_data="plans")])
    rows.append(_back_home_row("home"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_menu(plans: list[Plan], currency: str, back_callback: str = "plans") -> InlineKeyboardMarkup:
    currency_label = "⭐" if currency.upper() == "XTR" else "₽"
    rows = [
        [InlineKeyboardButton(text=f"{plan.title} — {plan.price} {currency_label}", callback_data=f"pay:{plan.code}")]
        for plan in plans
    ]
    rows.append(_back_home_row(back_callback))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_menu(yookassa_enabled: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="plans:stars")]]
    if yookassa_enabled:
        rows.insert(0, [InlineKeyboardButton(text="⚡ СБП через ЮKassa", callback_data="plans:sbp")])
    rows.append(_back_home_row("home"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sbp_plans_menu(plans: list[Plan]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_plan_label_with_saving(plan, plans, "₽"), callback_data=f"sbp:create:{plan.code}")]
        for plan in plans
    ]
    rows.append(_back_home_row("plans"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sbp_payment_menu(order_id: int, confirmation_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Перейти к оплате", url=confirmation_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"sbp:check:{order_id}")],
            _back_home_row("plans:sbp"),
        ]
    )


def trial_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Получить пробный период", callback_data="trial:activate")],
            _back_home_row("home"),
        ]
    )


def instructions_os_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Android", callback_data="instructions:android")],
            [InlineKeyboardButton(text="🍎 iPhone / iPad", callback_data="instructions:ios")],
            _back_home_row("home"),
        ]
    )


def instructions_ios_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Как подключить подписку к HAPP", callback_data="instr:ios_happ:0")],
            [InlineKeyboardButton(text="Что делать если в App Store нет HAPP", callback_data="instr:ios_appstore:0")],
            _back_home_row("instructions"),
        ]
    )


def instructions_android_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Как подключить подписку к HAPP", callback_data="instr:android_happ:0")],
            [InlineKeyboardButton(text="Что делать если в Google Play нет HAPP", callback_data="instr:android_googleplay:0")],
            _back_home_row("instructions"),
        ]
    )


def instruction_step_menu(
    *,
    key: str,
    index: int,
    total: int,
    link: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if index > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"instr:{key}:{index - 1}"))
    nav.append(InlineKeyboardButton(text=f"{index + 1} из {total}", callback_data="noop"))
    if index < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"instr:{key}:{index + 1}"))
    rows.append(nav)
    if link and len(link) <= COPY_TEXT_LIMIT:
        rows.append([InlineKeyboardButton(text="📋 Скопировать ссылку", copy_text=CopyTextButton(text=link))])
    rows.append([InlineKeyboardButton(text="🏠 Главная", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referrals_menu(referral_link: str) -> InlineKeyboardMarkup:
    share_text = "Привет! Попробуй ANDREVPN, тут можно получить VPN-доступ через Telegram."
    share_url = "https://t.me/share/url?url={url}&text={text}".format(
        url=quote(referral_link, safe=""),
        text=quote(share_text, safe=""),
    )
    rows = []
    if len(referral_link) <= COPY_TEXT_LIMIT:
        rows.append([InlineKeyboardButton(text="📋 Скопировать ссылку", copy_text=CopyTextButton(text=referral_link))])
    rows.extend(
        [
            [InlineKeyboardButton(text="📤 Поделиться с другом", url=share_url)],
            _back_home_row("home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_categories_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Проблема с оплатой", callback_data="support:payment")],
            [InlineKeyboardButton(text="🔗 Не подключается VPN", callback_data="support:vpn")],
            [InlineKeyboardButton(text="🐢 Низкая скорость", callback_data="support:speed")],
            [InlineKeyboardButton(text="📱 Проблема с HAPP", callback_data="support:happ")],
            [InlineKeyboardButton(text="👨‍💻 Написать оператору", callback_data="support:operator")],
            _back_home_row("home"),
        ]
    )


def support_hint_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Всё заработало", callback_data="support:done")],
            [InlineKeyboardButton(text="👨‍💻 Нужна помощь оператора", callback_data="support:operator")],
            _back_home_row("support"),
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin:add")],
            [InlineKeyboardButton(text="🖥 Сервер", callback_data="admin:server")],
            [InlineKeyboardButton(text="🏠 Главная", callback_data="home")],
        ]
    )


def admin_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_back_home_row("admin")])


def admin_grant_days_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="3 дня", callback_data="admin:add:days:3"),
                InlineKeyboardButton(text="30 дней", callback_data="admin:add:days:30"),
            ],
            [
                InlineKeyboardButton(text="60 дней", callback_data="admin:add:days:60"),
                InlineKeyboardButton(text="90 дней", callback_data="admin:add:days:90"),
            ],
            [InlineKeyboardButton(text="✏️ Другой срок", callback_data="admin:add:custom")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:add:cancel")],
        ]
    )


def admin_grant_confirm_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="admin:add:confirm"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="admin:add:cancel"),
            ],
        ]
    )


def success_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Подключить VPN", callback_data="connection")],
            [InlineKeyboardButton(text="👤 Моя подписка", callback_data="profile")],
            [InlineKeyboardButton(text="🏠 Главная", callback_data="home")],
        ]
    )


def back_menu(back_callback: str = "home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_back_home_row(back_callback)])


def _back_home_row(back_callback: str) -> list[InlineKeyboardButton]:
    if back_callback == "home":
        return [InlineKeyboardButton(text="🏠 Главная", callback_data="home")]
    return [
        InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback),
        InlineKeyboardButton(text="🏠 Главная", callback_data="home"),
    ]


def _plan_label_with_saving(plan: Plan, plans: list[Plan], currency_label: str) -> str:
    label = f"{plan.title} — {plan.price} {currency_label}"
    saving = _plan_saving(plan, plans)
    if saving > 0:
        label += f" · выгода {saving} {currency_label}"
    return label


def _plan_saving(plan: Plan, plans: list[Plan]) -> int:
    month_plans = [item for item in plans if item.days == 30 and item.price > 0]
    if not month_plans or plan.days <= 30 or plan.days % 30 != 0:
        return 0
    expected = month_plans[0].price * (plan.days // 30)
    return max(0, expected - plan.price)
