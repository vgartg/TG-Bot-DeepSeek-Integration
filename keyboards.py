from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("📋 Инструкция по применению", callback_data='menu_instruction')],
        [InlineKeyboardButton("🆓 4 бесплатных вопроса", callback_data='menu_free')],
        [InlineKeyboardButton("💰 Платные вопросы", callback_data='menu_paid')],
        [InlineKeyboardButton("♾️ Подписка на безлимит", callback_data='menu_subscription')],
        [InlineKeyboardButton("📄 Оферта", callback_data='menu_offer')],
        [InlineKeyboardButton("📢 Поделиться Скорой юридической", callback_data='menu_share')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_instruction_menu():
    """Меню инструкции"""
    keyboard = [
        [InlineKeyboardButton("📖 Инструкция", callback_data='show_instruction')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_free_questions_menu(free_left):
    """Меню бесплатных вопросов"""
    keyboard = [
        [InlineKeyboardButton(f"📝 Ответ на вопрос ({free_left} осталось)", callback_data='free_text')],
        [InlineKeyboardButton(f"📎 Ответ с загрузкой документов ({free_left} осталось)", callback_data='free_file')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_paid_questions_menu():
    """Меню платных вопросов"""
    keyboard = [
        [InlineKeyboardButton("📝 Ответ на вопрос (100 руб.)", callback_data='paid_text')],
        [InlineKeyboardButton("📎 Ответ с загрузкой документов (200 руб.)", callback_data='paid_file')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_subscription_menu():
    """Меню подписки"""
    keyboard = [
        [InlineKeyboardButton("2 недели - 1000 руб.", callback_data='sub_2weeks')],
        [InlineKeyboardButton("1 месяц - 1500 руб.", callback_data='sub_1month')],
        [InlineKeyboardButton("3 месяца - 3000 руб.", callback_data='sub_3months')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_offer_menu():
    """Меню оферты"""
    keyboard = [
        [InlineKeyboardButton("📄 Оферта", callback_data='show_offer')],
        [InlineKeyboardButton("🔒 Политика конфиденциальности", callback_data='show_privacy')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_share_menu():
    """Меню 'Поделиться'"""
    keyboard = [
        [InlineKeyboardButton("🔗 Поделиться ссылкой", callback_data='share_link')],
        [InlineKeyboardButton("📱 Поделиться QR-кодом", callback_data='share_qr')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_button():
    """Кнопка отмены"""
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data='main_menu')]]
    return InlineKeyboardMarkup(keyboard)