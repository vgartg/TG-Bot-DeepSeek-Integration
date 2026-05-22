import asyncio
import logging
import os
import tempfile
import traceback

from telegram import BotCommand, LabeledPrice, Update
from telegram.error import BadRequest
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from .config import (
    ADMIN_IDS,
    BOT_TOKEN,
    CURRENCY,
    INSTRUCTION_TEXT,
    OFFER_TEXT,
    PRICES,
    PRIVACY_TEXT,
    PROVIDER_TOKEN,
    RETURN_MONEY_TEXT,
    WELCOME_MESSAGE,
)
from .database import db
from .deepseek_api import deepseek_api
from .keyboards import (
    get_admin_menu,
    get_ask_question_menu,
    get_cancel_button,
    get_free_questions_menu,
    get_instruction_menu,
    get_instruction_view_menu,
    get_issued_receipt_control,
    get_main_menu,
    get_offer_menu,
    get_offer_view_menu,
    get_paid_questions_menu,
    get_pending_receipt_control,
    get_privacy_menu,
    get_return_money_menu,
    get_share_after_link_menu,
    get_share_after_qr_menu,
    get_share_initial_menu,
    get_subscription_menu,
)
from .models import User
from .utils import check_file_type, format_answer, generate_qr_code, get_file_size_mb

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_QUESTION, WAITING_FILE_QUESTION = range(2)


class LegalBot:
    def __init__(self):
        self.application = None
        self.user_states = {}

    # ---------- Вспомогательные методы ----------

    async def safe_edit_message(self, query, text, reply_markup=None):
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
            return True
        except BadRequest as e:
            if "Message is not modified" in str(e):
                await query.answer()
                return False
            elif "There is no text in the message to edit" in str(e):
                await query.answer()
                await query.message.reply_text(text=text, reply_markup=reply_markup)
                return False
            else:
                raise

    async def safe_reply_photo(self, query, photo, caption, reply_markup=None):
        try:
            await query.message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await query.message.reply_text(caption, reply_markup=reply_markup)

    def _is_admin(self, user_id):
        return user_id in ADMIN_IDS

    async def _get_has_subscription(self, user_id):
        """Проверяет, активна ли у пользователя подписка."""
        session = db.get_session()
        stats = db.get_user_stats(session, user_id)
        session.close()
        return stats['has_subscription'] if stats else False

    async def _get_main_menu_kb(self, user_id):
        """Получить клавиатуру главного меню с учётом прав и подписки."""
        has_sub = await self._get_has_subscription(user_id)
        is_admin = self._is_admin(user_id)
        return get_main_menu(is_admin=is_admin, has_subscription=has_sub)

    # ---------- Команды ----------

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        session = db.get_session()
        db.get_or_create_user(session, user.id, user.username, user.first_name, user.last_name)
        paid_requests = db.get_unused_paid_requests(session, user.id)
        session.close()

        kb = await self._get_main_menu_kb(user.id)
        if update.message:
            await update.message.reply_text(WELCOME_MESSAGE, reply_markup=kb)
        else:
            await update.callback_query.message.reply_text(WELCOME_MESSAGE, reply_markup=kb)

        if paid_requests:
            await update.message.reply_text(
                f"📋 У Вас есть неиспользованные оплаченные вопросы: {len(paid_requests)}.\n"
                f"Вы можете использовать их в меню 'Платные вопросы'.",
                reply_markup=kb,
            )

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        kb = await self._get_main_menu_kb(update.effective_user.id)
        await update.message.reply_text("Главное меню:", reply_markup=kb)

    # ---------- Основной обработчик меню ----------

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик меню (все callback, кроме тех, что уходят в ConversationHandler)"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        session = db.get_session()
        user_stats = db.get_user_stats(session, user_id)
        session.close()

        has_subscription = user_stats['has_subscription'] if user_stats else False
        kb_main = await self._get_main_menu_kb(user_id)

        if query.data == 'main_menu':
            await query.message.reply_text("Главное меню:", reply_markup=kb_main)

        elif query.data == 'menu_instruction':
            await self.safe_edit_message(query, "Инструкция по применению:", reply_markup=get_instruction_view_menu())

        elif query.data == 'show_instruction':
            await self.safe_edit_message(query, INSTRUCTION_TEXT, reply_markup=get_instruction_menu())

        elif query.data == 'menu_free':
            free_left = user_stats['free_requests_left'] if user_stats else 4
            has_sub = user_stats['has_subscription'] if user_stats else False

            message_text = f"У Вас осталось бесплатных вопросов: {free_left}\n\n"
            if has_sub:
                message_text += "📱 У Вас активна подписка, поэтому Вы можете задавать вопросы без ограничений.\n\n"
            message_text += "Выберите тип вопроса:"

            await self.safe_edit_message(query, message_text, reply_markup=get_free_questions_menu())

        elif query.data == 'menu_paid':
            session = db.get_session()
            paid_requests_text = db.get_unused_paid_requests(session, user_id, 'text')
            paid_requests_file = db.get_unused_paid_requests(session, user_id, 'file')
            session.close()

            text_count = len(paid_requests_text)
            file_count = len(paid_requests_file)

            message_text = "Выберите тип платного вопроса:\n\n"
            if text_count > 0:
                message_text += f"📝 Обычный вопрос - У Вас есть неиспользованные оплаченные вопросы: {text_count}\n"
            else:
                message_text += "📝 Обычный вопрос - 200 руб.\n"
            if file_count > 0:
                message_text += (
                    f"📎 Вопрос с загрузкой документов - У Вас есть неиспользованные оплаченные вопросы: {file_count}\n"
                )
            else:
                message_text += "📎 Вопрос с загрузкой документов - 300 руб.\n"
            message_text += "\nЕсли у Вас есть оплаченные вопросы, они будут использованы в первую очередь.\n"
            message_text += (
                "Если у Вас оформлена подписка, то плата за вопросы не будет запрашиваться, пока подписка активна"
            )

            await self.safe_edit_message(query, message_text, reply_markup=get_paid_questions_menu())

        elif query.data == 'menu_subscription':
            if has_subscription:
                sub_info = user_stats['subscription_info']
                end_date = sub_info['end'].strftime("%d.%m.%Y")
                await self.safe_edit_message(
                    query,
                    f"✅ У Вас активна подписка!\n\n"
                    f"📅 Тип подписки: {sub_info['type']}\n"
                    f"📅 Действует до: {end_date}\n\n"
                    f"С подпиской Вы можете задавать неограниченное количество вопросов.\n"
                    f"Выберите действие:",
                    reply_markup=kb_main,
                )
            else:
                await self.safe_edit_message(
                    query,
                    "Выберите вариант подписки:\n\n"
                    "📅 Безлимит на 2 недели - 1000 руб.\n"
                    "📅 Безлимит на 1 месяц - 1500 руб.\n"
                    "📅 Безлимит на 3 месяца - 3000 руб.\n\n"
                    "Подписка даёт право на неограниченное количество запросов, на указанный период (как с документами, так и без).",
                    reply_markup=get_subscription_menu(),
                )

        elif query.data == 'menu_offer':
            await self.safe_edit_message(
                query, "Оферта, политика конфиденциальности и возврата средств:", reply_markup=get_offer_view_menu()
            )

        elif query.data == 'show_offer':
            await self.safe_edit_message(query, OFFER_TEXT, reply_markup=get_offer_menu())

        elif query.data == 'show_privacy':
            await self.safe_edit_message(query, PRIVACY_TEXT, reply_markup=get_privacy_menu())

        elif query.data == 'show_return_money':
            await self.safe_edit_message(query, RETURN_MONEY_TEXT, reply_markup=get_return_money_menu())

        elif query.data == 'menu_share':
            await self.safe_edit_message(query, "Поделиться с друзьями:", reply_markup=get_share_initial_menu())

        elif query.data == 'share_link':
            bot_username = context.bot.username
            share_url = f"https://t.me/{bot_username}"
            await self.safe_edit_message(
                query,
                "Приглашайте друзей!\n"
                f"Ссылка на бота: {share_url}\n"
                "Просто скопируйте эту ссылку и отправьте её Вашим друзьям и знакомым.",
                reply_markup=get_share_after_link_menu(),
            )

        elif query.data == 'share_qr':
            bot_username = context.bot.username
            share_url = f"https://t.me/{bot_username}"
            await self.safe_edit_message(
                query, "QR-код для приглашения друзей:", reply_markup=get_share_after_qr_menu()
            )
            qr_code = generate_qr_code(share_url, context.bot)
            if qr_code:
                await self.safe_reply_photo(
                    query, qr_code, "Просто отсканируйте этот код", reply_markup=get_share_after_qr_menu()
                )
            else:
                await query.message.reply_text(
                    "Не удалось сгенерировать QR-код.", reply_markup=get_share_after_qr_menu()
                )

        elif query.data == 'ask_question':
            await self.safe_edit_message(query, "Выберите тип вопроса:", reply_markup=get_ask_question_menu())

        elif query.data == 'sub_text':
            context.user_data['question_type'] = 'subscription'
            context.user_data['waiting_for'] = 'text'
            await self.safe_edit_message(
                query,
                "📝 Напишите ваш юридический вопрос:\n\n🔘 Ответ может занять до 1-2 минут.",
                reply_markup=get_cancel_button(),
            )
            return WAITING_QUESTION

        elif query.data == 'sub_file':
            context.user_data['question_type'] = 'subscription'
            context.user_data['waiting_for'] = 'file'
            context.user_data['files'] = []
            context.user_data['file_context'] = []
            await self.safe_edit_message(
                query,
                "📎 Отправьте файл (PDF, DOCX, TXT) и ваш вопрос:\n\n"
                "🔘 Максимальный размер файла: 20 МБ\n"
                "🔘 Можно отправить несколько файлов, затем написать вопрос",
                reply_markup=get_cancel_button(),
            )
            return WAITING_FILE_QUESTION

        elif query.data.startswith('sub_'):
            if query.data in ['sub_text', 'sub_file']:
                logger.warning(f"Попытка обработать {query.data} как покупку подписки – пропущено")
                return

            if has_subscription:
                await query.message.reply_text(
                    "⏳ У Вас уже есть активная подписка. Вы не можете оформить новую, пока действует текущая.",
                    reply_markup=kb_main,
                )
                return

            if query.data == 'sub_2weeks':
                payload = 'subscription_2weeks'
                title = "Подписка на 2 недели"
                description = "Безлимитный доступ на 2 недели"
                price = PRICES['subscription_2weeks']
            elif query.data == 'sub_1month':
                payload = 'subscription_1month'
                title = "Подписка на 1 месяц"
                description = "Безлимитный доступ на 1 месяц"
                price = PRICES['subscription_1month']
            elif query.data == 'sub_3months':
                payload = 'subscription_3months'
                title = "Подписка на 3 месяца"
                description = "Безлимитный доступ на 3 месяца"
                price = PRICES['subscription_3months']
            else:
                return

            user = query.from_user
            username = user.username
            need_phone = username is None or username.strip() == ""

            try:
                await context.bot.send_invoice(
                    chat_id=user_id,
                    title=title,
                    description=description,
                    payload=payload,
                    provider_token=PROVIDER_TOKEN,
                    currency=CURRENCY,
                    prices=[LabeledPrice(title, price)],
                    need_phone_number=need_phone,
                    need_email=False,
                    send_phone_number_to_provider=need_phone,
                    send_email_to_provider=False,
                )
            except Exception as e:
                logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                await query.message.reply_text(
                    "❌ Не удалось отправить счёт для оплаты. Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                    reply_markup=kb_main,
                )

        elif query.data in ['free_text', 'paid_text']:
            is_free = query.data == 'free_text'
            user_id = query.from_user.id

            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            if is_free:
                if user_stats and user_stats['free_requests_left'] <= 0:
                    kb = await self._get_main_menu_kb(user_id)
                    await self.safe_edit_message(
                        query,
                        "❌ У Вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=kb,
                    )
                    return

                context.user_data['question_type'] = 'free'
                context.user_data['waiting_for'] = 'text'
                await self.safe_edit_message(
                    query,
                    "📝 Напишите ваш юридический вопрос:\n\n🔘 Ответ может занять до 1-2 минут.",
                    reply_markup=get_cancel_button(),
                )
                return WAITING_QUESTION

            else:
                session = db.get_session()
                paid_requests = db.get_unused_paid_requests(session, user_id, 'text')
                user_stats = db.get_user_stats(session, user_id)
                has_sub = user_stats['has_subscription'] if user_stats else False
                session.close()

                if has_sub or paid_requests:
                    if has_sub:
                        context.user_data['question_type'] = 'subscription'
                    else:
                        paid_request = paid_requests[0]
                        context.user_data['paid_request_id'] = paid_request.id
                        context.user_data['question_type'] = 'paid'

                    context.user_data['waiting_for'] = 'text'
                    await self.safe_edit_message(
                        query,
                        "📝 Напишите ваш юридический вопрос:\n\n🔘 Ответ может занять до 1-2 минут.",
                        reply_markup=get_cancel_button(),
                    )
                    return WAITING_QUESTION
                else:
                    payload = 'question_text'
                    title = "Обычный вопрос"
                    description = "Обычный вопрос без загрузки документов"
                    price = PRICES['question_text']
                    context.user_data['pending_question_type'] = 'paid_text'

                    user = query.from_user
                    username = user.username
                    need_phone = username is None or username.strip() == ""

                    try:
                        await context.bot.send_invoice(
                            chat_id=user_id,
                            title=title,
                            description=description,
                            payload=payload,
                            provider_token=PROVIDER_TOKEN,
                            currency=CURRENCY,
                            prices=[LabeledPrice("Обычный вопрос", price)],
                            need_phone_number=need_phone,
                            need_email=False,
                            send_phone_number_to_provider=need_phone,
                            send_email_to_provider=False,
                        )
                    except Exception as e:
                        logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                        kb = await self._get_main_menu_kb(user_id)
                        await query.message.reply_text(
                            "❌ Не удалось отправить счёт для оплаты. Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                            reply_markup=kb,
                        )

        elif query.data in ['free_file', 'paid_file']:
            is_free = query.data == 'free_file'
            user_id = query.from_user.id

            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            if is_free:
                if user_stats and user_stats['free_requests_left'] <= 0:
                    kb = await self._get_main_menu_kb(user_id)
                    await self.safe_edit_message(
                        query,
                        "❌ У Вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=kb,
                    )
                    return

                context.user_data['question_type'] = 'free'
                context.user_data['waiting_for'] = 'file'
                context.user_data['files'] = []
                context.user_data['file_context'] = []
                await self.safe_edit_message(
                    query,
                    "📎 Отправьте файл (PDF, DOCX, TXT) и ваш вопрос:\n\n"
                    "🔘 Максимальный размер файла: 20 МБ\n"
                    "🔘 Можно отправить несколько файлов, затем написать вопрос",
                    reply_markup=get_cancel_button(),
                )
                return WAITING_FILE_QUESTION

            else:
                session = db.get_session()
                paid_requests = db.get_unused_paid_requests(session, user_id, 'file')
                user_stats = db.get_user_stats(session, user_id)
                has_sub = user_stats['has_subscription'] if user_stats else False
                session.close()

                if has_sub or paid_requests:
                    if has_sub:
                        context.user_data['question_type'] = 'subscription'
                    else:
                        paid_request = paid_requests[0]
                        context.user_data['paid_request_id'] = paid_request.id
                        context.user_data['question_type'] = 'paid'

                    context.user_data['waiting_for'] = 'file'
                    context.user_data['files'] = []
                    context.user_data['file_context'] = []
                    await self.safe_edit_message(
                        query,
                        "📎 Отправьте файл (PDF, DOCX, TXT) и ваш вопрос:\n\n"
                        "🔘 Максимальный размер файла: 20 МБ\n"
                        "🔘 Можно отправить несколько файлов, затем написать вопрос",
                        reply_markup=get_cancel_button(),
                    )
                    return WAITING_FILE_QUESTION
                else:
                    payload = 'question_file'
                    title = "Вопрос с загрузкой документов"
                    description = "Вопрос с загрузкой документов"
                    price = PRICES['question_file']
                    context.user_data['pending_question_type'] = 'paid_file'

                    user = query.from_user
                    username = user.username
                    need_phone = username is None or username.strip() == ""

                    try:
                        await context.bot.send_invoice(
                            chat_id=user_id,
                            title=title,
                            description=description,
                            payload=payload,
                            provider_token=PROVIDER_TOKEN,
                            currency=CURRENCY,
                            prices=[LabeledPrice("Вопрос с загрузкой документов", price)],
                            need_phone_number=need_phone,
                            need_email=False,
                            send_phone_number_to_provider=need_phone,
                            send_email_to_provider=False,
                        )
                    except Exception as e:
                        logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                        kb = await self._get_main_menu_kb(user_id)
                        await query.message.reply_text(
                            "❌ Не удалось отправить счёт для оплаты. Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                            reply_markup=kb,
                        )

        elif query.data == 'admin_panel':
            if not self._is_admin(user_id):
                await query.message.reply_text("У Вас нет доступа к этой панели.", reply_markup=kb_main)
                return

            session = db.get_session()
            pending_count = db.count_pending_receipts(session)
            session.close()

            await self.safe_edit_message(
                query,
                f"🛠️ Админ панель\n\nНеобработанных платежей: {pending_count}\n\nВыберите действие:",
                reply_markup=get_admin_menu(pending_count),
            )

        elif query.data == 'admin_pending':
            if not self._is_admin(user_id):
                return

            session = db.get_session()
            pending_list = db.get_pending_receipts(session)
            session.close()

            if not pending_list:
                session = db.get_session()
                pending_count = db.count_pending_receipts(session)
                session.close()
                await self.safe_edit_message(
                    query,
                    "✅ Нет необработанных платежей. Все чеки готовы.",
                    reply_markup=get_admin_menu(pending_count),
                )
                return

            context.user_data['pending_receipts'] = [pr.id for pr in pending_list]
            context.user_data['pending_index'] = 0
            await self._show_pending_receipt(update, context, query)

        elif query.data == 'admin_next_pending':
            if not self._is_admin(user_id):
                return
            idx = context.user_data.get('pending_index', 0) + 1
            context.user_data['pending_index'] = idx
            await self._show_pending_receipt(update, context, query)

        elif query.data == 'admin_prev_pending':
            if not self._is_admin(user_id):
                return
            idx = context.user_data.get('pending_index', 0) - 1
            context.user_data['pending_index'] = idx
            await self._show_pending_receipt(update, context, query)

        elif query.data.startswith('admin_mark_issued_'):
            if not self._is_admin(user_id):
                return
            paid_request_id = int(query.data.replace('admin_mark_issued_', ''))
            session = db.get_session()
            success = db.mark_receipt_issued(session, paid_request_id)
            session.close()

            if success:
                if 'pending_receipts' in context.user_data:
                    try:
                        context.user_data['pending_receipts'].remove(paid_request_id)
                    except ValueError:
                        pass
                await self._show_pending_receipt(update, context, query)
            else:
                await query.message.reply_text("❌ Ошибка при отметке чека.", reply_markup=kb_main)

        elif query.data == 'admin_issued':
            if not self._is_admin(user_id):
                return

            session = db.get_session()
            issued_list = db.get_issued_receipts(session)
            pending_count = db.count_pending_receipts(session)
            session.close()

            if not issued_list:
                await self.safe_edit_message(query, "📭 Нет готовых чеков.", reply_markup=get_admin_menu(pending_count))
                return

            context.user_data['issued_receipts'] = [pr.id for pr in issued_list]
            context.user_data['issued_index'] = 0
            await self._show_issued_receipt(update, context, query)

        elif query.data == 'admin_next_issued':
            if not self._is_admin(user_id):
                return
            idx = context.user_data.get('issued_index', 0) + 1
            context.user_data['issued_index'] = idx
            await self._show_issued_receipt(update, context, query)

        elif query.data == 'admin_prev_issued':
            if not self._is_admin(user_id):
                return
            idx = context.user_data.get('issued_index', 0) - 1
            context.user_data['issued_index'] = idx
            await self._show_issued_receipt(update, context, query)

    # ---------- Методы для отображения чеков в админ-панели ----------

    async def _show_pending_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
        if query is None:
            query = update.callback_query

        pending_ids = context.user_data.get('pending_receipts', [])
        idx = context.user_data.get('pending_index', 0)

        if not pending_ids or idx < 0 or idx >= len(pending_ids):
            session = db.get_session()
            pending_list = db.get_pending_receipts(session)
            pending_count = db.count_pending_receipts(session)
            session.close()
            if not pending_list:
                await self.safe_edit_message(
                    query,
                    "✅ Нет необработанных платежей. Все чеки готовы.",
                    reply_markup=get_admin_menu(pending_count),
                )
                return
            context.user_data['pending_receipts'] = [pr.id for pr in pending_list]
            context.user_data['pending_index'] = 0
            idx = 0
            paid_request_id = pending_list[0].id
        else:
            paid_request_id = pending_ids[idx]

        session = db.get_session()
        paid_request = db.get_paid_request_by_id(session, paid_request_id)
        if not paid_request:
            session.close()
            context.user_data['pending_receipts'].remove(paid_request_id)
            await self._show_pending_receipt(update, context, query)
            return

        user = session.query(User).filter(User.user_id == paid_request.user_id).first()
        session.close()

        username = f"@{user.username}" if user and user.username else "—"
        first_name = user.first_name if user and user.first_name else "—"
        phone = paid_request.phone_number or "—"
        email = paid_request.email or "—"
        amount_rub = paid_request.amount / 100
        date_str = paid_request.paid_at.strftime("%d.%m.%Y %H:%M")

        text = (
            f"📋 **Платёж (неготовый чек)**\n\n"
            f"🆔 ID: `{paid_request.id}`\n"
            f"💰 Сумма: {amount_rub} {paid_request.currency}\n"
            f"📅 Дата/время: {date_str}\n"
            f"👤 Пользователь: {username} (ID: {paid_request.user_id})\n"
            f"👤 Имя: {first_name}\n"
            f"📞 Телефон: {phone}\n"
            f"📧 Email: {email}\n"
            f"Тип: {paid_request.request_type}\n"
        )

        has_next = idx + 1 < len(context.user_data['pending_receipts'])
        has_prev = idx > 0

        await self.safe_edit_message(
            query, text, reply_markup=get_pending_receipt_control(paid_request_id, has_next, has_prev)
        )

    async def _show_issued_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
        if query is None:
            query = update.callback_query

        issued_ids = context.user_data.get('issued_receipts', [])
        idx = context.user_data.get('issued_index', 0)

        if not issued_ids or idx < 0 or idx >= len(issued_ids):
            session = db.get_session()
            issued_list = db.get_issued_receipts(session)
            pending_count = db.count_pending_receipts(session)
            session.close()
            if not issued_list:
                await self.safe_edit_message(query, "📭 Нет готовых чеков.", reply_markup=get_admin_menu(pending_count))
                return
            context.user_data['issued_receipts'] = [pr.id for pr in issued_list]
            context.user_data['issued_index'] = 0
            idx = 0
            paid_request_id = issued_list[0].id
        else:
            paid_request_id = issued_ids[idx]

        session = db.get_session()
        paid_request = db.get_paid_request_by_id(session, paid_request_id)
        if not paid_request:
            session.close()
            context.user_data['issued_receipts'].remove(paid_request_id)
            await self._show_issued_receipt(update, context, query)
            return

        user = session.query(User).filter(User.user_id == paid_request.user_id).first()
        session.close()

        username = f"@{user.username}" if user and user.username else "—"
        first_name = user.first_name if user and user.first_name else "—"
        phone = paid_request.phone_number or "—"
        email = paid_request.email or "—"
        amount_rub = paid_request.amount / 100
        date_str = paid_request.paid_at.strftime("%d.%m.%Y %H:%M")

        text = (
            f"✅ **Платёж (чек готов)**\n\n"
            f"🆔 ID: `{paid_request.id}`\n"
            f"💰 Сумма: {amount_rub} {paid_request.currency}\n"
            f"📅 Дата/время: {date_str}\n"
            f"👤 Пользователь: {username} (ID: {paid_request.user_id})\n"
            f"👤 Имя: {first_name}\n"
            f"📞 Телефон: {phone}\n"
            f"📧 Email: {email}\n"
            f"Тип: {paid_request.request_type}\n"
        )

        has_next = idx + 1 < len(context.user_data['issued_receipts'])
        has_prev = idx > 0

        await self.safe_edit_message(query, text, reply_markup=get_issued_receipt_control(has_next, has_prev))

    # ---------- Обработчики платежей ----------

    async def pre_checkout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.pre_checkout_query
        try:
            await query.answer(ok=True)
            logger.info(f"Pre-checkout approved for query {query.id}")
        except Exception as e:
            logger.error(f"Error in pre-checkout: {e}\n{traceback.format_exc()}")
            await query.answer(ok=False, error_message="Произошла ошибка при обработке платежа")

    async def successful_payment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            payment = update.message.successful_payment
            user_id = update.effective_user.id
            payload = payment.invoice_payload

            logger.info(
                f"Successful payment from user {user_id}, payload: {payload}, amount: {payment.total_amount / 100} {payment.currency}"
            )

            order_info = payment.order_info
            phone_number = order_info.phone_number if order_info else None
            email = order_info.email if order_info else None
            payment_id = payment.provider_payment_charge_id

            await update.message.reply_text(
                f"✅ Платеж успешно завершен!\n\n💰 Сумма: {payment.total_amount / 100} {payment.currency}\n"
            )

            if payload.startswith('subscription_'):
                if payload == 'subscription_2weeks':
                    sub_type, days = '2weeks', 14
                    amount = PRICES['subscription_2weeks']
                elif payload == 'subscription_1month':
                    sub_type, days = '1month', 30
                    amount = PRICES['subscription_1month']
                elif payload == 'subscription_3months':
                    sub_type, days = '3months', 90
                    amount = PRICES['subscription_3months']
                else:
                    sub_type, days = 'unknown', 0
                    amount = 0

                session = db.get_session()
                success = db.activate_subscription(session, user_id, sub_type, days)

                paid_request = db.add_paid_request(
                    session,
                    user_id,
                    'subscription',
                    amount,
                    CURRENCY,
                    payment_id,
                    phone_number=phone_number,
                    email=email,
                )
                session.close()

                if success and paid_request:
                    kb = await self._get_main_menu_kb(user_id)
                    await update.message.reply_text(
                        f"🎉 Подписка успешно активирована!\n\n"
                        f"⭐ Теперь у Вас безлимитный доступ.\n"
                        f"⏳ Срок действия: {sub_type}\n\n"
                        f"Выберите дальнейшее действие:",
                        reply_markup=kb,
                    )
                    await self._notify_admins_about_payment(
                        context, user_id, amount, 'subscription', payment_id, phone_number, email
                    )
                else:
                    await update.message.reply_text(
                        "❌ Ошибка при активации подписки. Пожалуйста, обратитесь в поддержку.",
                        reply_markup=await self._get_main_menu_kb(user_id),
                    )

            elif payload in ['question_text', 'question_file']:
                request_type = 'text' if payload == 'question_text' else 'file'
                amount = PRICES[payload]

                session = db.get_session()
                paid_request = db.add_paid_request(
                    session, user_id, request_type, amount, CURRENCY, payment_id, phone_number=phone_number, email=email
                )

                if not paid_request:
                    await update.message.reply_text(
                        "❌ Ошибка при сохранении оплаченного вопроса. Пожалуйста, обратитесь в поддержку.",
                        reply_markup=await self._get_main_menu_kb(user_id),
                    )
                    session.close()
                    return

                context.user_data['paid_request_id'] = paid_request.id
                context.user_data['question_type'] = 'paid'
                context.user_data['waiting_for'] = request_type

                if request_type == 'file':
                    context.user_data['files'] = []
                    context.user_data['file_context'] = []

                session.close()

                await update.message.reply_text(
                    "Теперь напишите ваш юридический вопрос:", reply_markup=get_cancel_button()
                )

                await self._notify_admins_about_payment(
                    context, user_id, amount, request_type, payment_id, phone_number, email
                )

                return WAITING_QUESTION if request_type == 'text' else WAITING_FILE_QUESTION

        except Exception as e:
            logger.error(f"Error in successful_payment_callback: {e}\n{traceback.format_exc()}")
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке платежа. Пожалуйста, обратитесь в поддержку.",
                reply_markup=await self._get_main_menu_kb(update.effective_user.id),
            )

    async def _notify_admins_about_payment(self, context, user_id, amount, request_type, payment_id, phone, email):
        """Отправить уведомление всем администраторам о новом платеже."""
        session = db.get_session()
        user = session.query(User).filter(User.user_id == user_id).first()
        session.close()

        username = f"@{user.username}" if user and user.username else f"ID {user_id}"
        first_name = user.first_name if user and user.first_name else "—"

        type_desc = {'text': 'текстовый вопрос', 'file': 'вопрос с файлом', 'subscription': 'подписка'}.get(
            request_type, request_type
        )

        text = (
            f"🔔 **Новый платёж!**\n\n"
            f"💰 Сумма: {amount / 100} RUB\n"
            f"📅 Тип: {type_desc}\n"
            f"👤 Пользователь: {username}\n"
            f"👤 Имя: {first_name}\n"
            f"🆔 ID: {user_id}\n"
            f"📞 Телефон: {phone or '—'}\n"
            f"📧 Email: {email or '—'}\n"
            f"💳 ID платежа: `{payment_id}`\n\n"
            f"Данные доступны в разделе **«Неготовые чеки»** админ‑панели."
        )

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=text)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")

    # ---------- Обработчики текстовых вопросов и файлов ----------

    async def handle_text_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстового вопроса"""
        user_id = update.message.from_user.id
        question_text = update.message.text

        session = db.get_session()
        user_stats = db.get_user_stats(session, user_id)

        question_type = context.user_data.get('question_type', 'free')
        paid_request_id = context.user_data.get('paid_request_id')

        has_subscription = user_stats['has_subscription'] if user_stats else False

        if question_type == 'free' and not has_subscription:
            if user_stats and user_stats['free_requests_left'] <= 0:
                await update.message.reply_text(
                    "❌ У Вас закончились бесплатные вопросы.\n\n"
                    "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                    reply_markup=await self._get_main_menu_kb(user_id),
                )
                session.close()
                return ConversationHandler.END

            user = session.query(User).filter(User.user_id == user_id).first()
            if user and user.free_requests_left > 0:
                user.free_requests_left -= 1
                session.commit()

        elif question_type == 'paid' and not has_subscription and not paid_request_id:
            paid_requests = db.get_unused_paid_requests(session, user_id, 'text')
            if not paid_requests:
                await update.message.reply_text(
                    "❌ У Вас нет оплаченных вопросов. Пожалуйста, оплатите вопрос.",
                    reply_markup=await self._get_main_menu_kb(user_id),
                )
                session.close()
                return ConversationHandler.END
            else:
                paid_request = paid_requests[0]
                paid_request_id = paid_request.id
                context.user_data['paid_request_id'] = paid_request_id

        processing_msg = await update.message.reply_text("⏳ Обрабатываю ваш вопрос...\nЭто может занять 1-2 минуты.")

        try:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: deepseek_api.process_query(user_query=question_text, use_search=True, use_deepthink=True),
                ),
                timeout=180,
            )

            if 'error' in result:
                await processing_msg.edit_text(f"❌ Ошибка: {result['error']}")
                session.close()
                return ConversationHandler.END

            db_request = db.add_request(session, user_id, question_text, result['answer'], result['tokens_used'], False)

            if question_type == 'paid' and paid_request_id:
                db.use_paid_request(session, paid_request_id, db_request.id if db_request else None)
                if 'paid_request_id' in context.user_data:
                    del context.user_data['paid_request_id']

            session.close()

            answer_parts = format_answer(result['answer'])
            for i, part in enumerate(answer_parts):
                if i == 0:
                    await processing_msg.edit_text(part)
                else:
                    await update.message.reply_text(part)

            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            free_left = user_stats['free_requests_left'] if user_stats else 0

            if has_subscription or question_type == 'subscription':
                await update.message.reply_text(
                    "✅ Ответ сформирован!\n\n📱 У Вас активна подписка\n\nВыберите дальнейшее действие:",
                    reply_markup=await self._get_main_menu_kb(user_id),
                )
            else:
                await update.message.reply_text(
                    f"✅ Ответ сформирован!\n"
                    f"Бесплатных вопросов осталось: {free_left}\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=await self._get_main_menu_kb(user_id),
                )

        except TimeoutError:
            await processing_msg.edit_text(
                "⏱️ Обработка вопроса занимает больше времени, чем ожидалось.\n"
                "Пожалуйста, подождите еще немного или попробуйте позже."
            )
            logger.error("Timeout error processing question")
            session.close()
        except Exception as e:
            logger.error(f"Error processing question: {e}\n{traceback.format_exc()}")
            try:
                await processing_msg.edit_text(
                    f"❌ Произошла ошибка при обработке запроса:\n\n"
                    f"Детали ошибки: {str(e)[:500]}\n\n"
                    f"Пожалуйста, попробуйте позже или обратитесь в поддержку."
                )
            except Exception:
                pass
            session.close()

        return ConversationHandler.END

    async def handle_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка загруженного файла"""
        if 'files' not in context.user_data:
            context.user_data['files'] = []
        if 'file_context' not in context.user_data:
            context.user_data['file_context'] = []
        if 'file_ids' not in context.user_data:
            context.user_data['file_ids'] = []
        if 'file_texts' not in context.user_data:
            context.user_data['file_texts'] = []

        if not update.message.document:
            await update.message.reply_text("Пожалуйста, отправьте файл в формате PDF, DOCX или TXT")
            return WAITING_FILE_QUESTION

        file = update.message.document
        telegram_file_id = file.file_id
        file_name = file.file_name or "document"

        if not check_file_type(file_name):
            await update.message.reply_text(
                "❌ Неподдерживаемый тип файла.\n"
                "Поддерживаемые форматы: PDF, DOCX, TXT\n\n"
                "Пожалуйста, отправьте файл в одном из этих форматов."
            )
            return WAITING_FILE_QUESTION

        try:
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, file_name)

            loading_msg = await update.message.reply_text(f"📥 Скачиваю файл '{file_name}'...")

            tg_file = await context.bot.get_file(telegram_file_id)
            await tg_file.download_to_drive(file_path)

            file_size_mb = get_file_size_mb(file_path)
            if file_size_mb > 20:
                await loading_msg.edit_text("❌ Файл слишком большой (максимум 20 МБ)")
                os.remove(file_path)
                return WAITING_FILE_QUESTION

            context.user_data['files'].append(file_path)

            await loading_msg.edit_text("📤 Загружаю файл...")

            deepseek_file_id = None
            try:
                deepseek_file_id = deepseek_api.upload_file_to_deepseek(file_path)
                if deepseek_file_id:
                    logger.info(f"Файл '{file_name}' загружен в DeepSeek, file_id: {deepseek_file_id}")
                    context.user_data['file_ids'].append(deepseek_file_id)
                    file_info = {
                        'filename': file_name,
                        'file_id': deepseek_file_id,
                        'local_path': file_path,
                        'method': 'deepseek_upload',
                    }
                    context.user_data['file_context'].append(file_info)
                else:
                    raise Exception("Не удалось получить file_id от DeepSeek")
            except Exception as upload_error:
                logger.error(f"Ошибка загрузки в DeepSeek: {upload_error}")
                deepseek_file_id = None

            if not deepseek_file_id:
                await loading_msg.edit_text(f"⏳ Пробую резервный метод для файла '{file_name}'...")
                try:
                    ext = os.path.splitext(file_name)[1].lower()
                    if ext in ['.txt', '.pdf', '.docx']:
                        text, success = deepseek_api.extract_text_from_file(file_path)
                        if success and text and len(text.strip()) > 50:
                            context.user_data['file_texts'].append(
                                {'filename': file_name, 'text': text[:10000], 'size': len(text)}
                            )
                            file_info = {
                                'filename': file_name,
                                'method': 'local_text_extraction',
                                'text_length': len(text),
                            }
                            context.user_data['file_context'].append(file_info)
                            await loading_msg.edit_text(
                                f"✅ Файл '{file_name}' обработан\n"
                                f"Загружено файлов: {len(context.user_data['files'])}\n\n"
                                "Теперь напишите ваш вопрос к этим документам:"
                            )
                            return WAITING_FILE_QUESTION
                except Exception as extract_error:
                    logger.error(f"Ошибка при локальном извлечении текста: {extract_error}")

                await loading_msg.edit_text(
                    f"⚠️ Файл '{file_name}' сохранён, но не удалось обработать.\n"
                    f"Загружено файлов: {len(context.user_data['files'])}\n\n"
                    "Вы можете продолжить загрузку файлов или задать вопрос."
                )
                return WAITING_FILE_QUESTION

            await loading_msg.edit_text(
                f"✅ Файл '{file_name}' успешно загружен!\n"
                f"Загружено файлов: {len(context.user_data['files'])}\n"
                "Теперь напишите ваш вопрос к этим документам:"
            )
            return WAITING_FILE_QUESTION

        except Exception as e:
            logger.error(f"Критическая ошибка в handle_file: {e}\n{traceback.format_exc()}")
            try:
                error_msg = await update.message.reply_text(
                    f"❌ Произошла ошибка при обработке файла.\nОшибка: {str(e)[:200]}"
                )
                await asyncio.sleep(2)
                await error_msg.edit_text("Пожалуйста, попробуйте загрузить файл еще раз.")
            except Exception:
                pass
            return WAITING_FILE_QUESTION

    async def handle_file_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка вопроса по файлам"""
        user_id = update.message.from_user.id
        question_text = update.message.text

        if 'files' not in context.user_data or not context.user_data['files']:
            await update.message.reply_text("Сначала загрузите файлы, затем задайте вопрос")
            return WAITING_FILE_QUESTION

        if 'file_texts' not in context.user_data or not context.user_data['file_texts']:
            await update.message.reply_text("⚠️ Тексты файлов не были сохранены. Пожалуйста, загрузите файлы заново.")
            return ConversationHandler.END

        session = db.get_session()
        user_stats = db.get_user_stats(session, user_id)

        question_type = context.user_data.get('question_type', 'free')
        paid_request_id = context.user_data.get('paid_request_id')
        has_subscription = user_stats['has_subscription'] if user_stats else False

        if not has_subscription:
            if question_type == 'free':
                if user_stats and user_stats['free_requests_left'] <= 0:
                    await update.message.reply_text(
                        "❌ У Вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=await self._get_main_menu_kb(user_id),
                    )
                    for file_path in context.user_data['files']:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    session.close()
                    return ConversationHandler.END
                user = session.query(User).filter(User.user_id == user_id).first()
                if user and user.free_requests_left > 0:
                    user.free_requests_left -= 1
                    session.commit()
            elif question_type == 'paid' and not paid_request_id:
                paid_requests = db.get_unused_paid_requests(session, user_id, 'file')
                if not paid_requests:
                    await update.message.reply_text(
                        "❌ У Вас нет оплаченных вопросов с документами. Пожалуйста, оплатите вопрос.",
                        reply_markup=await self._get_main_menu_kb(user_id),
                    )
                    for file_path in context.user_data['files']:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    session.close()
                    return ConversationHandler.END
                else:
                    paid_request = paid_requests[0]
                    paid_request_id = paid_request.id
                    context.user_data['paid_request_id'] = paid_request_id

        processing_msg = await update.message.reply_text(
            "🔍 Анализирую документы и готовлю ответ...\nЭто может занять 1-2 минуты."
        )

        try:
            file_texts = context.user_data.get('file_texts', [])
            if not file_texts:
                await processing_msg.edit_text(
                    "❌ Не удалось найти тексты загруженных файлов. Пожалуйста, загрузите файлы заново."
                )
                session.close()
                for file_path in context.user_data.get('files', []):
                    if os.path.exists(file_path):
                        os.remove(file_path)
                return ConversationHandler.END

            total_text_length = sum(f['size'] for f in file_texts if 'size' in f)
            logger.info(f"Передаю {len(file_texts)} файлов, общий объем текста: {total_text_length} символов")

            prepared_file_texts = []
            for file_data in file_texts:
                filename = file_data['filename']
                text = file_data['text']
                max_per_file = 10000
                if len(text) > max_per_file:
                    half = max_per_file // 2
                    text = (
                        text[:half] + "\n\n...[СРЕДНЯЯ ЧАСТЬ ТЕКСТА ПРОПУЩЕНА ИЗ-ЗА ОГРАНИЧЕНИЙ]...\n\n" + text[-half:]
                    )
                prepared_file_texts.append({'filename': filename, 'text': text})

            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: deepseek_api.process_query(
                        user_query=question_text, file_texts=prepared_file_texts, use_search=True, use_deepthink=True
                    ),
                ),
                timeout=180,
            )

            for file_path in context.user_data.get('files', []):
                if os.path.exists(file_path):
                    os.remove(file_path)

            if 'error' in result:
                await processing_msg.edit_text(f"❌ Ошибка: {result['error']}")
                session.close()
                return ConversationHandler.END

            files_info = str(len(context.user_data['files'])) + " файлов"
            total_tokens = result['tokens_used']

            db_request = db.add_request(
                session, user_id, question_text, result['answer'], total_tokens, True, files_info
            )

            if question_type == 'paid' and paid_request_id:
                db.use_paid_request(session, paid_request_id, db_request.id if db_request else None)
                if 'paid_request_id' in context.user_data:
                    del context.user_data['paid_request_id']

            session.close()

            answer_parts = format_answer(result['answer'])
            for i, part in enumerate(answer_parts):
                if i == 0:
                    await processing_msg.edit_text(part)
                else:
                    await update.message.reply_text(part)

            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            if has_subscription or question_type == 'subscription':
                await update.message.reply_text(
                    "✅ Анализ завершен!\n\n📱 У Вас активна подписка\n\nВыберите дальнейшее действие:",
                    reply_markup=await self._get_main_menu_kb(user_id),
                )
            else:
                await update.message.reply_text(
                    "✅ Анализ завершен!\n\nВыберите дальнейшее действие:",
                    reply_markup=await self._get_main_menu_kb(user_id),
                )

        except TimeoutError:
            await processing_msg.edit_text(
                "⏱️ Анализ документов занимает больше времени, чем ожидалось.\n"
                "Пожалуйста, подождите еще немного или попробуйте позже."
            )
            logger.error("Timeout error processing file question")
            for file_path in context.user_data.get('files', []):
                if os.path.exists(file_path):
                    os.remove(file_path)
            session.close()
        except Exception as e:
            logger.error(f"Error processing file question: {e}\n{traceback.format_exc()}")
            for file_path in context.user_data.get('files', []):
                if os.path.exists(file_path):
                    os.remove(file_path)
            try:
                await processing_msg.edit_text(
                    f"❌ Произошла ошибка при анализе документов:\n\n"
                    f"Детали: {str(e)[:300]}\n\n"
                    f"Пожалуйста, попробуйте позже."
                )
            except Exception:
                pass
            session.close()

        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущего действия"""
        if 'files' in context.user_data:
            for file_path in context.user_data['files']:
                if os.path.exists(file_path):
                    os.remove(file_path)

        if 'paid_request_id' in context.user_data:
            paid_request_id = context.user_data['paid_request_id']
            session = db.get_session()
            paid_request = db.get_paid_request_by_id(session, paid_request_id)
            if paid_request and not paid_request.used:
                request_type = "текстовый" if paid_request.request_type == 'text' else "с документами"
                await update.message.reply_text(
                    f"✅ Оплаченный вопрос сохранён!\n\n"
                    f"📋 У Вас остался оплаченный {request_type} вопрос.\n"
                    f"Вы можете использовать его позже в меню 'Платные вопросы'.",
                    reply_markup=await self._get_main_menu_kb(update.effective_user.id),
                )
            session.close()

        for key in list(context.user_data.keys()):
            if not key.startswith('paid_'):
                context.user_data[key] = None
                del context.user_data[key]

        await update.message.reply_text(
            "Действие отменено. Оплаченные вопросы сохранены для будущего использования.",
            reply_markup=await self._get_main_menu_kb(update.effective_user.id),
        )
        return ConversationHandler.END

    # ---------- Обработчики ошибок и неподдерживаемых медиа ----------

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if "Conflict: terminated by other getUpdates request" in str(context.error):
            logger.warning("Multiple bot instances detected, ignoring error")
            return
        logger.error(f"Update {update} caused error {context.error}\n{traceback.format_exc()}")
        try:
            if context.user_data and 'files' in context.user_data:
                for file_path in context.user_data['files']:
                    if os.path.exists(file_path):
                        os.remove(file_path)
        except Exception:
            pass
        if update and update.effective_message:
            try:
                kb = await self._get_main_menu_kb(update.effective_user.id) if update.effective_user else None
                await update.effective_message.reply_text(
                    f"❌ Произошла ошибка:\n\nДетали: {str(context.error)[:500]}\n\nПожалуйста, попробуйте снова или обратитесь в поддержку.",
                    reply_markup=kb,
                )
            except Exception:
                pass

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        kb = await self._get_main_menu_kb(update.effective_user.id)
        await update.message.reply_text(
            "🎤 Мы еще не умеем отвечать на голосовые сообщения.\n\n"
            "Пожалуйста, воспользуйтесь кнопками из меню или напишите текст.",
            reply_markup=kb,
        )

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        kb = await self._get_main_menu_kb(update.effective_user.id)
        await update.message.reply_text(
            "📷 Фотографии не поддерживаются.\n\nПожалуйста, отправьте файл в формате PDF, DOCX или TXT.",
            reply_markup=kb,
        )

    async def handle_unsupported_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        kb = await self._get_main_menu_kb(update.effective_user.id)
        await update.message.reply_text(
            "📁 Этот тип медиа не поддерживается.\n\n"
            "Пожалуйста, отправьте текстовое сообщение или файл в формате PDF, DOCX, TXT.",
            reply_markup=kb,
        )

    async def handle_unexpected_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка неожиданных текстовых сообщений (когда ожидается вопрос)"""
        if context.user_data.get('paid_request_id') or context.user_data.get('question_type') in [
            'paid',
            'subscription',
            'free',
        ]:
            waiting_for = context.user_data.get('waiting_for', 'text')
            if waiting_for == 'text':
                await self.handle_text_question(update, context)
            elif waiting_for == 'file':
                await self.handle_file_question(update, context)
            return

        kb = await self._get_main_menu_kb(update.effective_user.id)
        await update.message.reply_text("Пожалуйста, используйте меню для навигации:", reply_markup=kb)

    # ---------- Настройка обработчиков ----------

    def setup_handlers(self):
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    self.handle_menu, pattern='^(free_text|free_file|paid_text|paid_file|sub_text|sub_file)$'
                )
            ],
            states={
                WAITING_QUESTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_question),
                    CallbackQueryHandler(self.cancel, pattern='^main_menu$'),
                ],
                WAITING_FILE_QUESTION: [
                    MessageHandler(filters.Document.ALL, self.handle_file),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_file_question),
                    CallbackQueryHandler(self.cancel, pattern='^main_menu$'),
                ],
            },
            fallbacks=[CommandHandler('cancel', self.cancel), CallbackQueryHandler(self.cancel, pattern='^main_menu$')],
            allow_reentry=True,
        )

        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("menu", self.menu_command))

        self.application.add_handler(
            CallbackQueryHandler(
                self.handle_menu, pattern='^(?!free_text|free_file|paid_text|paid_file|sub_text|sub_file).*$'
            )
        )

        self.application.add_handler(conv_handler)

        self.application.add_handler(PreCheckoutQueryHandler(self.pre_checkout_callback))
        self.application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment_callback))

        self.application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

        unsupported_media_filters = filters.VIDEO | filters.AUDIO | filters.VIDEO_NOTE | filters.ANIMATION
        self.application.add_handler(MessageHandler(unsupported_media_filters, self.handle_unsupported_media))

        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_unexpected_text))

        self.application.add_error_handler(self.error_handler)

    async def set_bot_commands(self, application):
        commands = [BotCommand("start", "Запустить Скорую Юридическую"), BotCommand("menu", "Главное меню")]
        await application.bot.set_my_commands(commands)

    def run(self):
        from telegram.ext import ApplicationBuilder

        self.application = (
            ApplicationBuilder()
            .token(BOT_TOKEN)
            .read_timeout(30)
            .write_timeout(30)
            .connect_timeout(30)
            .pool_timeout(30)
            .build()
        )

        self.setup_handlers()
        self.application.post_init = self.set_bot_commands

        logger.info("Бот запущен...")
        try:
            self.application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, close_loop=False)
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем.")
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")


def main():
    bot = LegalBot()
    bot.run()


if __name__ == '__main__':
    main()
