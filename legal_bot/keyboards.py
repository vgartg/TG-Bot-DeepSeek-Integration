from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu(is_admin=False, has_subscription=False):
    """Главное меню (динамическое — подписка и админка)."""
    keyboard = []

    if has_subscription:
        keyboard.append([InlineKeyboardButton("❓ Задать вопрос", callback_data='ask_question')])
    else:
        keyboard.append([InlineKeyboardButton("🆓 Бесплатные вопросы", callback_data='menu_free')])
        keyboard.append([InlineKeyboardButton("💰 Платные вопросы", callback_data='menu_paid')])

    keyboard.append([InlineKeyboardButton("📅 Подписка на безлимит", callback_data='menu_subscription')])
    keyboard.append([InlineKeyboardButton("📋 Инструкция по применению", callback_data='menu_instruction')])
    keyboard.append([InlineKeyboardButton("📑 Оферта", callback_data='menu_offer')])
    keyboard.append([InlineKeyboardButton("📤 Поделиться Скорой Юридической", callback_data='menu_share')])

    if is_admin:
        keyboard.append([InlineKeyboardButton("🛠️ Админ панель", callback_data='admin_panel')])

    return InlineKeyboardMarkup(keyboard)


def get_ask_question_menu():
    """Меню выбора типа вопроса при активной подписке."""
    keyboard = [
        [InlineKeyboardButton("📝 Текстовый вопрос", callback_data='sub_text')],
        [InlineKeyboardButton("📎 Вопрос с файлом", callback_data='sub_file')],
        [InlineKeyboardButton("« Назад", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_menu(pending_count):
    """Меню админ‑панели с отображением количества ожидающих чеков."""
    keyboard = [
        [InlineKeyboardButton(f"📋 Неготовые чеки ({pending_count})", callback_data='admin_pending')],
        [InlineKeyboardButton("✅ Готовые чеки", callback_data='admin_issued')],
        [InlineKeyboardButton("« Назад", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_pending_receipt_control(paid_request_id, has_next, has_prev):
    """Кнопки управления для одного неготового чека."""
    keyboard = [
        [InlineKeyboardButton("✅ Пометить как готовый", callback_data=f'admin_mark_issued_{paid_request_id}')]
    ]
    nav_buttons = []
    if has_prev:
        nav_buttons.append(InlineKeyboardButton("◀️ Предыдущий", callback_data='admin_prev_pending'))
    if has_next:
        nav_buttons.append(InlineKeyboardButton("⏩ Следующий", callback_data='admin_next_pending'))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("« Админ панель", callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)


def get_issued_receipt_control(has_next, has_prev):
    """Кнопки навигации для готовых чеков."""
    keyboard = []
    nav_buttons = []
    if has_prev:
        nav_buttons.append(InlineKeyboardButton("◀️ Предыдущий", callback_data='admin_prev_issued'))
    if has_next:
        nav_buttons.append(InlineKeyboardButton("⏩ Следующий", callback_data='admin_next_issued'))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("« Админ панель", callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)


def get_instruction_menu():
    keyboard = [[InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]]
    return InlineKeyboardMarkup(keyboard)

def get_instruction_view_menu():
    keyboard = [
        [InlineKeyboardButton("📋 Инструкция", callback_data='show_instruction')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_free_questions_menu():
    keyboard = [
        [InlineKeyboardButton("📝 Обычный вопрос", callback_data='free_text')],
        [InlineKeyboardButton("📎 Вопрос с загрузкой документов", callback_data='free_file')],
        [InlineKeyboardButton("↩️ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_paid_questions_menu():
    keyboard = [
        [InlineKeyboardButton("📝 Обычный вопрос", callback_data='paid_text')],
        [InlineKeyboardButton("📎 Вопрос с загрузкой документов", callback_data='paid_file')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_subscription_menu():
    keyboard = [
        [InlineKeyboardButton("2 недели - 1000 руб.", callback_data='sub_2weeks')],
        [InlineKeyboardButton("1 месяц - 1500 руб.", callback_data='sub_1month')],
        [InlineKeyboardButton("3 месяца - 3000 руб.", callback_data='sub_3months')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_offer_menu():
    keyboard = [
        [InlineKeyboardButton("🔒 Политика конфиденциальности", callback_data='show_privacy')],
        [InlineKeyboardButton("💸 Политика возврата денежных средств", callback_data='show_return_money')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_privacy_menu():
    keyboard = [
        [InlineKeyboardButton("📑 Оферта", callback_data='show_offer')],
        [InlineKeyboardButton("💸 Политика возврата денежных средств", callback_data='show_return_money')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_return_money_menu():
    keyboard = [
        [InlineKeyboardButton("📑 Оферта", callback_data='show_offer')],
        [InlineKeyboardButton("🔒 Политика конфиденциальности", callback_data='show_privacy')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_offer_view_menu():
    keyboard = [
        [InlineKeyboardButton("📑 Оферта", callback_data='show_offer')],
        [InlineKeyboardButton("🔒 Политика конфиденциальности и обработки персональных данных", callback_data='show_privacy')],
        [InlineKeyboardButton("💸 Политика возврата денежных средств", callback_data='show_return_money')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_share_after_link_menu():
    keyboard = [
        [InlineKeyboardButton("📲 Поделиться QR-кодом", callback_data='share_qr')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_share_after_qr_menu():
    keyboard = [
        [InlineKeyboardButton("🔗 Поделиться ссылкой", callback_data='share_link')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_share_initial_menu():
    keyboard = [
        [InlineKeyboardButton("🔗 Поделиться ссылкой", callback_data='share_link')],
        [InlineKeyboardButton("📲 Поделиться QR-кодом", callback_data='share_qr')],
        [InlineKeyboardButton("⭐ Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_button():
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data='main_menu')]]
    return InlineKeyboardMarkup(keyboard)
