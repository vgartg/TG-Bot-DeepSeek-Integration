import logging
from telegram import Update, BotCommand, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
    PreCheckoutQueryHandler
)
from telegram.error import BadRequest, TimedOut, NetworkError
import os
from datetime import datetime, timedelta
import traceback
import json
import tempfile
import asyncio
import time

from config import (
    BOT_TOKEN, WELCOME_MESSAGE, INSTRUCTION_TEXT, OFFER_TEXT, PRIVACY_TEXT,
    PROVIDER_TOKEN, CURRENCY, PRICES, RETURN_MONEY_TEXT
)
from database import db
from keyboards import *
from deepseek_api import deepseek_api
from utils import generate_qr_code, format_answer, check_file_type, get_file_size_mb

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
WAITING_QUESTION, WAITING_FILE_QUESTION = range(2)

class LegalBot:
    def __init__(self):
        self.application = None
        self.user_states = {}  # Хранение состояний пользователей

    async def safe_edit_message(self, query, text, reply_markup=None):
        """Безопасное редактирование сообщения с обработкой ошибки 'Message is not modified'"""
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
            return True
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Сообщение уже имеет тот же контент, просто отвечаем на callback_query
                await query.answer()
                return False
            elif "There is no text in the message to edit" in str(e):
                # Нельзя редактировать сообщение без текста (например, фото с QR-кодом)
                await query.answer()
                await query.message.reply_text(text=text, reply_markup=reply_markup)
                return False
            else:
                raise  # Другие ошибки пробрасываем дальше

    async def safe_reply_photo(self, query, photo, caption, reply_markup=None):
        """Безопасная отправка фото с обработкой кнопки назад"""
        try:
            await query.message.reply_photo(
                photo=photo,
                caption=caption,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await query.message.reply_text(
                caption,
                reply_markup=reply_markup
            )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user

        # Сохраняем пользователя в БД
        session = db.get_session()
        db_user = db.get_or_create_user(
            session,
            user.id,
            user.username,
            user.first_name,
            user.last_name
        )
        
        # Проверяем, есть ли у пользователя неиспользованные оплаченные вопросы
        paid_requests = db.get_unused_paid_requests(session, user.id)
        
        session.close()

        # Отправляем приветственное сообщение
        if update.message:
            await update.message.reply_text(
                WELCOME_MESSAGE,
                reply_markup=get_main_menu()
            )
        else:
            await update.callback_query.message.reply_text(
                WELCOME_MESSAGE,
                reply_markup=get_main_menu()
            )
            
        # Если есть неиспользованные оплаченные вопросы, показываем уведомление
        if paid_requests:
            await update.message.reply_text(
                f"📋 У вас есть неиспользованные оплаченные вопросы: {len(paid_requests)}.\n"
                f"Вы можете использовать их в меню 'Платные вопросы'.",
                reply_markup=get_main_menu()
            )

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /menu"""
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_menu()
        )

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик меню"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        session = db.get_session()
        user_stats = db.get_user_stats(session, user_id)
        session.close()

        if query.data == 'main_menu':
            # Всегда отправляем новое сообщение для главного меню
            await query.message.reply_text(
                "Главное меню:",
                reply_markup=get_main_menu()
            )

        elif query.data == 'menu_instruction':
            await self.safe_edit_message(
                query,
                "Инструкция по применению:",
                reply_markup=get_instruction_view_menu()
            )

        elif query.data == 'show_instruction':
            await self.safe_edit_message(
                query,
                INSTRUCTION_TEXT,
                reply_markup=get_instruction_menu()
            )

        elif query.data == 'menu_free':
            free_left = user_stats['free_requests_left'] if user_stats else 4
            await self.safe_edit_message(
                query,
                f"У вас осталось бесплатных вопросов: {free_left}\n\n"
                f"Выберите тип вопроса:",
                reply_markup=get_free_questions_menu(free_left)
            )

        elif query.data == 'menu_paid':
            # Проверяем наличие неиспользованных оплаченных вопросов
            session = db.get_session()
            paid_requests_text = db.get_unused_paid_requests(session, user_id, 'text')
            paid_requests_file = db.get_unused_paid_requests(session, user_id, 'file')
            session.close()
            
            text_count = len(paid_requests_text)
            file_count = len(paid_requests_file)
            
            message_text = "Выберите тип платного вопроса:\n\n"
            
            if text_count > 0:
                message_text += f"📝 Ответ на вопрос - У вас есть неиспользованные оплаченные вопросы: {text_count}\n"
            else:
                message_text += "📝 Ответ на вопрос - 100 руб.\n"
                
            if file_count > 0:
                message_text += f"📎 Ответ с загрузкой документов - У вас есть неиспользованные оплаченные вопросы: {file_count}\n"
            else:
                message_text += "📎 Ответ с загрузкой документов - 200 руб.\n"
                
            message_text += "\nЕсли у вас есть оплаченные вопросы, они будут использованы в первую очередь.\nЕсли у вас оформлена подписка, то плата за вопросы не будет запрашиваться, пока подписка активна"
            
            await self.safe_edit_message(
                query,
                message_text,
                reply_markup=get_paid_questions_menu()
            )

        elif query.data == 'menu_subscription':
            # Проверяем, есть ли активная подписка
            has_subscription = user_stats['has_subscription'] if user_stats else False
            
            if has_subscription:
                subscription_info = user_stats['subscription_info']
                end_date = subscription_info['end'].strftime("%d.%m.%Y")
                
                await self.safe_edit_message(
                    query,
                    f"✅ У вас активна подписка!\n\n"
                    f"📅 Тип подписки: {subscription_info['type']}\n"
                    f"📅 Действует до: {end_date}\n\n"
                    f"С подпиской вы можете задавать неограниченное количество вопросов.\n"
                    f"Выберите действие:",
                    reply_markup=get_main_menu()
                )
            else:
                await self.safe_edit_message(
                    query,
                    "Выберите вариант подписки:\n\n"
                    "📅 Безлимит на 2 недели - 1000 руб.\n"
                    "📅 Безлимит на 1 месяц - 1500 руб.\n"
                    "📅 Безлимит на 3 месяца - 3000 руб.\n\n"
                    "Подписка дает право на неограниченное количество запросов, на указанный период (как с документами, так и без).",
                    reply_markup=get_subscription_menu()
                )

        elif query.data.startswith('sub_'):
            # Проверяем, есть ли уже активная подписка
            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()
            
            has_subscription = user_stats['has_subscription'] if user_stats else False
            
            if has_subscription:
                await query.message.reply_text(
                    "❌ У вас уже есть активная подписка. Вы не можете оформить новую, пока действует текущая.",
                    reply_markup=get_main_menu()
                )
                return
                
            # Обработка выбора подписки - отправляем счет
            user_id = query.from_user.id

            if query.data == 'sub_2weeks':
                payload = 'subscription_2weeks'
                title = "Подписка на 2 недели"
                description = "Безлимитный доступ на 2 недели"
                price = PRICES['subscription_2weeks']
                prices = [LabeledPrice("Подписка на 2 недели", price)]

            elif query.data == 'sub_1month':
                payload = 'subscription_1month'
                title = "Подписка на 1 месяц"
                description = "Безлимитный доступ на 1 месяц"
                price = PRICES['subscription_1month']
                prices = [LabeledPrice("Подписка на 1 месяц", price)]

            elif query.data == 'sub_3months':
                payload = 'subscription_3months'
                title = "Подписка на 3 месяца"
                description = "Безлимитный доступ на 3 месяца"
                price = PRICES['subscription_3months']
                prices = [LabeledPrice("Подписка на 3 месяца", price)]

            try:
                # Отправляем счет
                await context.bot.send_invoice(
                    chat_id=user_id,
                    title=title,
                    description=description,
                    payload=payload,
                    provider_token=PROVIDER_TOKEN,
                    currency=CURRENCY,
                    prices=prices,
                    need_phone_number=True,
                    send_phone_number_to_provider=True
                )

                # Отправляем сообщение с инструкцией для тестового режима
                if PROVIDER_TOKEN and 'TEST' in PROVIDER_TOKEN:
                    await query.message.reply_text(
                        "💳 Для оплаты используйте тестовые данные карты:\n"
                        "Номер: 1111 1111 1111 1026\n"
                        "Срок: 12/22\n"
                        "CVC: 000"
                    )

            except Exception as e:
                logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                await query.message.reply_text(
                    "❌ Не удалось отправить счет для оплаты. Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                    reply_markup=get_main_menu()
                )

        elif query.data == 'menu_offer':
            await self.safe_edit_message(
                query,
                "Оферта, политика конфиденциальности и возврата средств:",
                reply_markup=get_offer_view_menu()
            )

        elif query.data == 'show_offer':
            await self.safe_edit_message(
                query,
                OFFER_TEXT,
                reply_markup=get_offer_menu()
            )

        elif query.data == 'show_privacy':
            await self.safe_edit_message(
                query,
                PRIVACY_TEXT,
                reply_markup=get_privacy_menu()
            )

        elif query.data == 'show_return_money':
            await self.safe_edit_message(
                query,
                RETURN_MONEY_TEXT,
                reply_markup=get_return_money_menu()
            )

        elif query.data == 'menu_share':
            await self.safe_edit_message(
                query,
                "Поделиться с друзьями:",
                reply_markup=get_share_initial_menu()
            )

        elif query.data == 'share_link':
            bot_username = context.bot.username
            share_url = f"https://t.me/{bot_username}"
            await self.safe_edit_message(
                query,
                "Приглашайте друзей!\n"
                f"Ссылка на бота: {share_url}\n"
                "Просто скопируйте эту ссылку и отправьте её Вашим друзьям и знакомым.",
                reply_markup=get_share_after_link_menu()
            )

        elif query.data == 'share_qr':
            bot_username = context.bot.username
            share_url = f"https://t.me/{bot_username}"

            # Сначала редактируем текущее сообщение
            await self.safe_edit_message(
                query,
                "QR-код для приглашения друзей:",
                reply_markup=get_share_after_qr_menu()
            )

            # Затем отправляем фото с QR-кодом
            qr_code = generate_qr_code(share_url, context.bot)
            if qr_code:
                await self.safe_reply_photo(
                    query,
                    qr_code,
                    "Просто отсканируйте этот код",
                    reply_markup=get_share_after_qr_menu()
                )
            else:
                await query.message.reply_text(
                    "Не удалось сгенерировать QR-код.",
                    reply_markup=get_share_after_qr_menu()
                )

        elif query.data in ['free_text', 'paid_text']:
            # Начало текстового вопроса
            is_free = query.data == 'free_text'
            user_id = query.from_user.id

            # Проверяем доступ
            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            if is_free:
                # Бесплатный вопрос
                if user_stats and user_stats['free_requests_left'] <= 0:
                    await self.safe_edit_message(
                        query,
                        "❌ У вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=get_main_menu()
                    )
                    return

                context.user_data['question_type'] = 'free'
                context.user_data['waiting_for'] = 'text'

                await self.safe_edit_message(
                    query,
                    "📝 Напишите ваш юридический вопрос:\n\n"
                    "🔘 Ответ может занять до 1-2 минут.",
                    reply_markup=get_cancel_button()
                )
                return WAITING_QUESTION

            else:
                # Платный вопрос - проверяем наличие оплаченных вопросов
                session = db.get_session()
                paid_requests = db.get_unused_paid_requests(session, user_id, 'text')
                
                # Проверяем подписку
                user_stats = db.get_user_stats(session, user_id)
                has_subscription = user_stats['has_subscription'] if user_stats else False

                if has_subscription or paid_requests:
                    # Есть подписка или оплаченные вопросы
                    if has_subscription:
                        context.user_data['question_type'] = 'subscription'
                    else:
                        # Используем первый оплаченный вопрос
                        paid_request = paid_requests[0]
                        # Сохраняем ID оплаченного вопроса ДО закрытия сессии
                        paid_request_id = paid_request.id
                        context.user_data['paid_request_id'] = paid_request_id
                        context.user_data['question_type'] = 'paid'

                    context.user_data['waiting_for'] = 'text'

                    await self.safe_edit_message(
                        query,
                        "📝 Напишите ваш юридический вопрос:\n\n"
                        "🔘 Ответ может занять до 1-2 минут.",
                        reply_markup=get_cancel_button()
                    )
                    session.close()
                    return WAITING_QUESTION
                else:
                    # Нет оплаченных вопросов и подписки - предлагаем оплатить
                    session.close()
                    payload = 'question_text'
                    title = "Ответ на юридический вопрос"
                    description = "Ответ на один юридический вопрос без документов"
                    price = PRICES['question_text']
                    prices = [LabeledPrice("Ответ на вопрос", price)]

                    try:
                        # Сохраняем тип вопроса для последующей обработки
                        context.user_data['pending_question_type'] = 'paid_text'

                        await context.bot.send_invoice(
                            chat_id=user_id,
                            title=title,
                            description=description,
                            payload=payload,
                            provider_token=PROVIDER_TOKEN,
                            currency=CURRENCY,
                            prices=prices,
                            need_phone_number=True,
                            send_phone_number_to_provider=True
                        )

                        # Инструкция для тестового режима
                        if PROVIDER_TOKEN and 'TEST' in PROVIDER_TOKEN:
                            await query.message.reply_text(
                                "🔧 Для оплаты используйте тестовые данные карты:\n"
                                "Номер: 1111 1111 1111 1026\n"
                                "Срок: 12/22\n"
                                "CVC: 000"
                            )

                    except Exception as e:
                        logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                        await query.message.reply_text(
                            "❌ Не удалось отправить счет для оплаты. Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                            reply_markup=get_main_menu()
                        )

        elif query.data in ['free_file', 'paid_file']:
            # Начало вопроса с файлами
            is_free = query.data == 'free_file'
            user_id = query.from_user.id

            # Проверяем доступ
            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            if is_free:
                # Бесплатный вопрос с файлами
                if user_stats and user_stats['free_requests_left'] <= 0:
                    await self.safe_edit_message(
                        query,
                        "❌ У вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=get_main_menu()
                    )
                    return

                context.user_data['question_type'] = 'free'
                context.user_data['waiting_for'] = 'file'
                context.user_data['files'] = []
                context.user_data['file_context'] = []  # Для хранения контекста анализа файлов

                await self.safe_edit_message(
                    query,
                    "📎 Отправьте файл (PDF, DOCX, TXT) и ваш вопрос:\n\n"
                    "🔘 Максимальный размер файла: 20 МБ\n"
                    "🔘 Можно отправить несколько файлов, затем написать вопрос",
                    reply_markup=get_cancel_button()
                )
                return WAITING_FILE_QUESTION

            else:
                # Платный вопрос с файлами - проверяем наличие оплаченных вопросов
                session = db.get_session()
                paid_requests = db.get_unused_paid_requests(session, user_id, 'file')
                
                # Проверяем подписку
                user_stats = db.get_user_stats(session, user_id)
                has_subscription = user_stats['has_subscription'] if user_stats else False

                if has_subscription or paid_requests:
                    # Есть подписка или оплаченные вопросы
                    if has_subscription:
                        context.user_data['question_type'] = 'subscription'
                    else:
                        # Используем первый оплаченный вопрос
                        paid_request = paid_requests[0]
                        # Сохраняем ID оплаченного вопроса ДО закрытия сессии
                        paid_request_id = paid_request.id
                        context.user_data['paid_request_id'] = paid_request_id
                        context.user_data['question_type'] = 'paid'

                    context.user_data['waiting_for'] = 'file'
                    context.user_data['files'] = []
                    context.user_data['file_context'] = []

                    await self.safe_edit_message(
                        query,
                        "ЁЯУО Отправьте файл (PDF, DOCX, TXT) и ваш вопрос:\n\n"
                        "🔘 Максимальный размер файла: 20 МБ\n"
                        "🔘 Можно отправить несколько файлов, затем написать вопрос",
                        reply_markup=get_cancel_button()
                    )
                    session.close()
                    return WAITING_FILE_QUESTION
                else:
                    # Нет оплаченных вопросов и подписки - предлагаем оплатить
                    session.close()
                    payload = 'question_file'
                    title = "Ответ с анализом документов"
                    description = "Ответ на один юридический вопрос с анализом документов"
                    price = PRICES['question_file']
                    prices = [LabeledPrice("Ответ с документами", price)]

                    try:
                        # Сохраняем тип вопроса для последующей обработки
                        context.user_data['pending_question_type'] = 'paid_file'

                        await context.bot.send_invoice(
                            chat_id=user_id,
                            title=title,
                            description=description,
                            payload=payload,
                            provider_token=PROVIDER_TOKEN,
                            currency=CURRENCY,
                            prices=prices,
                            need_phone_number=True,
                            send_phone_number_to_provider=True
                        )

                        # Инструкция для тестового режима
                        if PROVIDER_TOKEN and 'TEST' in PROVIDER_TOKEN:
                            await query.message.reply_text(
                                "🔧 Для оплаты используйте тестовые данные карты:\n"
                                "Номер: 1111 1111 1111 1026\n"
                                "Срок: 12/22\n"
                                "CVC: 000"
                            )

                    except Exception as e:
                        logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                        await query.message.reply_text(
                            "❌ Не удалось отправить счет для оплаты. Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                            reply_markup=get_main_menu()
                        )

    async def pre_checkout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Предварительная проверка платежа"""
        query = update.pre_checkout_query
        try:
            # Всегда отвечаем утвердительно
            await query.answer(ok=True)
            logger.info(f"Pre-checkout approved for query {query.id}")
        except Exception as e:
            logger.error(f"Error in pre-checkout: {e}\n{traceback.format_exc()}")
            await query.answer(ok=False, error_message="Произошла ошибка при обработке платежа")

    async def successful_payment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Успешный платеж"""
        try:
            payment = update.message.successful_payment
            user_id = update.effective_user.id
            payload = payment.invoice_payload

            logger.info(f"Successful payment from user {user_id}, payload: {payload}, amount: {payment.total_amount / 100} {payment.currency}")

            if payload.startswith('subscription_'):
                # Активация подписки
                session = db.get_session()

                if payload == 'subscription_2weeks':
                    subscription_type = '2weeks'
                    duration_days = 14
                    duration_text = "2 недели"
                elif payload == 'subscription_1month':
                    subscription_type = '1month'
                    duration_days = 30
                    duration_text = "1 месяц"
                elif payload == 'subscription_3months':
                    subscription_type = '3months'
                    duration_days = 90
                    duration_text = "3 месяца"
                else:
                    subscription_type = 'unknown'
                    duration_days = 0
                    duration_text = "неизвестный период"

                # Активируем подписку в БД
                success = db.activate_subscription(session, user_id, subscription_type, duration_days)
                session.close()

                if success:
                    await update.message.reply_text(
                        f"✅ Подписка успешно активирована!\n\n"
                        f"🎉 Теперь у вас безлимитный доступ.\n"
                        f"📆 Срок действия: {duration_text}\n"
                        f"💰 Сумма оплаты: {payment.total_amount / 100} {payment.currency}\n\n"
                        f"Выберите дальнейшее действие:",
                        reply_markup=get_main_menu()
                    )
                else:
                    await update.message.reply_text(
                        "❌ Ошибка при активации подписки. Пожалуйста, обратитесь в поддержку.",
                        reply_markup=get_main_menu()
                    )

            elif payload in ['question_text', 'question_file']:
                # Оплата вопроса - сохраняем оплаченный вопрос в БД
                session = db.get_session()

                if payload == 'question_text':
                    request_type = 'text'
                    amount = PRICES['question_text']
                else:
                    request_type = 'file'
                    amount = PRICES['question_file']

                # Сохраняем оплаченный вопрос
                paid_request = db.add_paid_request(
                    session,
                    user_id,
                    request_type,
                    amount,
                    CURRENCY,
                    f"paid_{int(time.time())}"
                )

                if not paid_request:
                    await update.message.reply_text(
                        "❌ Ошибка при сохранении оплаченного вопроса. Пожалуйста, обратитесь в поддержку.",
                        reply_markup=get_main_menu()
                    )
                    session.close()
                    return

                # Сохраняем ID оплаченного запроса ДО закрытия сессии
                paid_request_id = paid_request.id
                session.close()

                # Сохраняем ID оплаченного вопроса в контексте
                context.user_data['paid_request_id'] = paid_request_id
                context.user_data['question_type'] = 'paid'
                context.user_data['waiting_for'] = request_type

                if request_type == 'file':
                    context.user_data['files'] = []
                    context.user_data['file_context'] = []

                await update.message.reply_text(
                    f"✅ Оплата прошла успешно!\n\n"
                    f"💰 Сумма: {payment.total_amount / 100} {payment.currency}\n"
                    f"📎 Теперь напишите ваш юридический вопрос:",
                    reply_markup=get_cancel_button()
                )

                # Возвращаем состояние ожидания вопроса
                return WAITING_QUESTION if request_type == 'text' else WAITING_FILE_QUESTION

        except Exception as e:
            logger.error(f"Error in successful_payment_callback: {e}\n{traceback.format_exc()}")
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке платежа. Пожалуйста, обратитесь в поддержку.",
                reply_markup=get_main_menu()
            )

    async def handle_text_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстового вопроса"""
        user_id = update.message.from_user.id
        question_text = update.message.text

        # Проверяем доступность запросов
        session = db.get_session()
        user_stats = db.get_user_stats(session, user_id)

        question_type = context.user_data.get('question_type', 'free')
        paid_request_id = context.user_data.get('paid_request_id')

        # Проверяем подписку
        has_subscription = user_stats['has_subscription'] if user_stats else False

        if not has_subscription:
            if question_type == 'free':
                if user_stats and user_stats['free_requests_left'] <= 0:
                    await update.message.reply_text(
                        "❌ У вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=get_main_menu()
                    )
                    session.close()
                    return ConversationHandler.END
            elif question_type == 'paid' and not paid_request_id:
                # Проверяем, есть ли оплаченные вопросы
                paid_requests = db.get_unused_paid_requests(session, user_id, 'text')
                if not paid_requests:
                    await update.message.reply_text(
                        "❌ У вас нет оплаченных вопросов. Пожалуйста, оплатите вопрос.",
                        reply_markup=get_main_menu()
                    )
                    session.close()
                    return ConversationHandler.END
                else:
                    # Используем первый оплаченный вопрос
                    paid_request = paid_requests[0]
                    paid_request_id = paid_request.id
                    context.user_data['paid_request_id'] = paid_request_id

        processing_msg = await update.message.reply_text(
            "⏳ Обрабатываю ваш вопрос...\n"
            "Это может занять 1-2 минуты."
        )

        try:
            # Отправляем запрос в DeepSeek с увеличенным таймаутом
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: deepseek_api.process_query(
                        user_query=question_text,
                        use_search=True,
                        use_deepthink=True
                    )
                ),
                timeout=180  # Увеличиваем таймаут до 3 минут
            )

            if 'error' in result:
                await processing_msg.edit_text(f"❌ Ошибка: {result['error']}")
                session.close()
                # Не удаляем оплаченный вопрос при ошибке
                return ConversationHandler.END

            # Сохраняем запрос в БД
            db_request = db.add_request(
                session,
                user_id,
                question_text,
                result['answer'],
                result['tokens_used'],
                False
            )

            # Если это платный вопрос, отмечаем его как использованный
            if question_type == 'paid' and paid_request_id:
                db.use_paid_request(session, paid_request_id, db_request.id if db_request else None)
                # Удаляем из контекста после использования
                if 'paid_request_id' in context.user_data:
                    del context.user_data['paid_request_id']

            # Списываем токен если нет подписки и вопрос бесплатный
            if not has_subscription and question_type == 'free':
                db.update_user_tokens(session, user_id, 'free')

            session.close()

            # Отправляем ответ частями
            answer_parts = format_answer(result['answer'])
            for i, part in enumerate(answer_parts):
                if i == 0:
                    await processing_msg.edit_text(part)
                else:
                    await update.message.reply_text(part)

            # Обновляем статистику
            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            free_left = user_stats['free_requests_left'] if user_stats else 0

            if has_subscription or question_type == 'subscription':
                await update.message.reply_text(
                    f"✅ Ответ сформирован!\n\n"
                    f"📊 У вас активна подписка\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )
            else:
                await update.message.reply_text(
                    f"✅ Ответ сформирован!\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )

        except asyncio.TimeoutError:
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
            except:
                pass
            session.close()

        return ConversationHandler.END

    async def handle_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка загруженного файла"""
        # Инициализируем структуры данных
        if 'files' not in context.user_data:
            context.user_data['files'] = []
        if 'file_context' not in context.user_data:
            context.user_data['file_context'] = []
        if 'file_ids' not in context.user_data:
            context.user_data['file_ids'] = []
        if 'file_texts' not in context.user_data:
            context.user_data['file_texts'] = []

        # Проверяем, что это документ (не фото и не голосовое)
        if not update.message.document:
            await update.message.reply_text(
                "Пожалуйста, отправьте файл в формате PDF, DOCX или TXT"
            )
            return WAITING_FILE_QUESTION

        file = update.message.document
        telegram_file_id = file.file_id
        file_name = file.file_name or "document"

        # Проверяем тип файла
        if not check_file_type(file_name):
            await update.message.reply_text(
                "❌ Неподдерживаемый тип файла.\n"
                "Поддерживаемые форматы: PDF, DOCX, TXT\n\n"
                "Пожалуйста, отправьте файл в одном из этих форматов."
            )
            return WAITING_FILE_QUESTION

        try:
            # Скачиваем файл от Telegram
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, file_name)

            loading_msg = await update.message.reply_text(f"📥 Скачиваю файл '{file_name}'...")

            # Скачиваем файл
            tg_file = await context.bot.get_file(telegram_file_id)
            await tg_file.download_to_drive(file_path)

            # Проверяем размер файла
            file_size_mb = get_file_size_mb(file_path)
            if file_size_mb > 20:
                await loading_msg.edit_text("❌ Файл слишком большой (максимум 20 МБ)")
                os.remove(file_path)
                return WAITING_FILE_QUESTION

            # Сохраняем путь к файлу
            context.user_data['files'].append(file_path)

            await loading_msg.edit_text(f"📤 Загружаю файл в DeepSeek API...")

            # Пытаемся загрузить файл в DeepSeek API
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
                        'method': 'deepseek_upload'
                    }
                    context.user_data['file_context'].append(file_info)
                else:
                    raise Exception("Не удалось получить file_id от DeepSeek")

            except Exception as upload_error:
                logger.error(f"Ошибка загрузки в DeepSeek: {upload_error}")
                deepseek_file_id = None

            # Если загрузка в DeepSeek не удалась, пробуем резервный метод
            if not deepseek_file_id:
                await loading_msg.edit_text(f"⏳ Пробую резервный метод для файла '{file_name}'...")

                # Для текстовых файлов пробуем извлечь текст локально
                try:
                    ext = os.path.splitext(file_name)[1].lower()
                    if ext in ['.txt', '.pdf', '.docx']:
                        text, success = deepseek_api.extract_text_from_file(file_path)
                        if success and text and len(text.strip()) > 50:
                            context.user_data['file_texts'].append({
                                'filename': file_name,
                                'text': text[:10000],
                                'size': len(text)
                            })

                            file_info = {
                                'filename': file_name,
                                'method': 'local_text_extraction',
                                'text_length': len(text)
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

                # Если ничего не сработало, просто сообщаем о загрузке
                await loading_msg.edit_text(
                    f"⚠️ Файл '{file_name}' сохранен, но не удалось обработать.\n"
                    f"Загружено файлов: {len(context.user_data['files'])}\n\n"
                    "Вы можете продолжить загрузку файлов или задать вопрос."
                )
                return WAITING_FILE_QUESTION

            # Если загрузка в DeepSeek удалась
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
                    f"❌ Произошла ошибка при обработке файла.\n"
                    f"Ошибка: {str(e)[:200]}"
                )

                await asyncio.sleep(2)
                await error_msg.edit_text(
                    "Пожалуйста, попробуйте загрузить файл еще раз."
                )
            except:
                pass

            return WAITING_FILE_QUESTION

    async def handle_file_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка вопроса по файлам"""
        user_id = update.message.from_user.id
        question_text = update.message.text

        if 'files' not in context.user_data or not context.user_data['files']:
            await update.message.reply_text("Сначала загрузите файлы, затем задайте вопрос")
            return WAITING_FILE_QUESTION

        # Проверяем, есть ли сохраненные тексты файлов
        if 'file_texts' not in context.user_data or not context.user_data['file_texts']:
            await update.message.reply_text(
                "⚠️ Тексты файлов не были сохранены. Пожалуйста, загрузите файлы заново."
            )
            return ConversationHandler.END

        # Проверяем доступ
        session = db.get_session()
        user_stats = db.get_user_stats(session, user_id)

        question_type = context.user_data.get('question_type', 'free')
        paid_request_id = context.user_data.get('paid_request_id')

        # Проверяем подписку
        has_subscription = user_stats['has_subscription'] if user_stats else False

        if not has_subscription:
            if question_type == 'free':
                if user_stats and user_stats['free_requests_left'] <= 0:
                    await update.message.reply_text(
                        "❌ У вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=get_main_menu()
                    )
                    # Удаляем временные файлы
                    for file_path in context.user_data['files']:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    session.close()
                    return ConversationHandler.END
            elif question_type == 'paid' and not paid_request_id:
                # Проверяем, есть ли оплаченные вопросы с файлами
                paid_requests = db.get_unused_paid_requests(session, user_id, 'file')
                if not paid_requests:
                    await update.message.reply_text(
                        "❌ У вас нет оплаченных вопросов с документами. Пожалуйста, оплатите вопрос.",
                        reply_markup=get_main_menu()
                    )
                    # Удаляем временные файлы
                    for file_path in context.user_data['files']:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    session.close()
                    return ConversationHandler.END
                else:
                    # Используем первый оплаченный вопрос
                    paid_request = paid_requests[0]
                    paid_request_id = paid_request.id
                    context.user_data['paid_request_id'] = paid_request_id

        processing_msg = await update.message.reply_text(
            "🔍 Анализирую документы и готовлю ответ...\n"
            "Это может занять 1-2 минуты."
        )

        try:
            # ВАЖНО: Используем сохраненные тексты файлов
            file_texts = context.user_data.get('file_texts', [])

            if not file_texts:
                await processing_msg.edit_text(
                    "❌ Не удалось найти тексты загруженных файлов. "
                    "Пожалуйста, загрузите файлы заново."
                )
                session.close()
                # Удаляем временные файлы
                for file_path in context.user_data.get('files', []):
                    if os.path.exists(file_path):
                        os.remove(file_path)
                return ConversationHandler.END

            # Логируем, что передаем
            total_text_length = sum(f['size'] for f in file_texts if 'size' in f)
            logger.info(f"Передаю {len(file_texts)} файлов, общий объем текста: {total_text_length} символов")

            # Подготавливаем тексты файлов для отправки
            prepared_file_texts = []
            for file_data in file_texts:
                filename = file_data['filename']
                text = file_data['text']

                # Ограничиваем размер каждого файла
                max_per_file = 10000
                if len(text) > max_per_file:
                    half = max_per_file // 2
                    text = text[:half] + "\n\n...[СРЕДНЯЯ ЧАСТЬ ТЕКСТА ПРОПУЩЕНА ИЗ-ЗА ОГРАНИЧЕНИЙ ДЛИНЫ]...\n\n" + text[-half:]

                prepared_file_texts.append({
                    'filename': filename,
                    'text': text
                })

            # Отправляем запрос с поиском, передавая ТЕКСТЫ файлов с увеличенным таймаутом
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: deepseek_api.process_query(
                        user_query=question_text,
                        file_texts=prepared_file_texts,
                        use_search=True,
                        use_deepthink=True
                    )
                ),
                timeout=180  # Увеличиваем таймаут до 3 минут
            )

            # Удаляем временные файлы
            for file_path in context.user_data['files']:
                if os.path.exists(file_path):
                    os.remove(file_path)

            if 'error' in result:
                await processing_msg.edit_text(f"❌ Ошибка: {result['error']}")
                session.close()
                # Не удаляем оплаченный вопрос при ошибке
                return ConversationHandler.END

            # Сохраняем запрос в БД
            files_info = str(len(context.user_data['files'])) + " файлов"
            total_tokens = result['tokens_used']

            db_request = db.add_request(
                session,
                user_id,
                question_text,
                result['answer'],
                total_tokens,
                True,
                files_info
            )

            # Если это платный вопрос, отмечаем его как использованный
            if question_type == 'paid' and paid_request_id:
                db.use_paid_request(session, paid_request_id, db_request.id if db_request else None)
                # Удаляем из контекста после использования
                if 'paid_request_id' in context.user_data:
                    del context.user_data['paid_request_id']

            # Списывание токена если нет подписки
            if not has_subscription and question_type == 'free':
                db.update_user_tokens(session, user_id, 'free')

            session.close()

            # Отправляем ответ частями
            answer_parts = format_answer(result['answer'])
            for i, part in enumerate(answer_parts):
                if i == 0:
                    await processing_msg.edit_text(part)
                else:
                    await update.message.reply_text(part)

            # Обновляем статистику
            session = db.get_session()
            user_stats = db.get_user_stats(session, user_id)
            session.close()

            free_left = user_stats['free_requests_left'] if user_stats else 0

            if has_subscription or question_type == 'subscription':
                await update.message.reply_text(
                    f"✅ Анализ завершен!\n\n"
                    f"📊 У вас активна подписка\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )
            else:
                await update.message.reply_text(
                    f"✅ Анализ завершен!\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )

        except asyncio.TimeoutError:
            await processing_msg.edit_text(
                "⏱️ Анализ документов занимает больше времени, чем ожидалось.\n"
                "Пожалуйста, подождите еще немного или попробуйте позже."
            )
            logger.error("Timeout error processing file question")
            # Удаляем временные файлы при таймауте
            for file_path in context.user_data.get('files', []):
                if os.path.exists(file_path):
                    os.remove(file_path)
            session.close()
        except Exception as e:
            logger.error(f"Error processing file question: {e}\n{traceback.format_exc()}")
            # Удаляем временные файлы при ошибке
            for file_path in context.user_data.get('files', []):
                if os.path.exists(file_path):
                    os.remove(file_path)

            try:
                await processing_msg.edit_text(
                    f"❌ Произошла ошибка при анализе документов:\n\n"
                    f"Детали: {str(e)[:300]}\n\n"
                    f"Пожалуйста, попробуйте позже."
                )
            except:
                pass
            session.close()

        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущего действия"""
        # Удаляем временные файлы если есть
        if 'files' in context.user_data:
            for file_path in context.user_data['files']:
                if os.path.exists(file_path):
                    os.remove(file_path)

        # Очищаем состояния, но НЕ удаляем оплаченные вопросы
        # Они остаются в базе данных для будущего использования
        if 'paid_request_id' in context.user_data:
            # Сохраняем ID оплаченного вопроса для информирования пользователя
            paid_request_id = context.user_data['paid_request_id']
            
            # Получаем информацию об оплаченном вопросе
            session = db.get_session()
            paid_request = session.query(db.PaidRequest).filter(db.PaidRequest.id == paid_request_id).first()
            
            if paid_request and not paid_request.used:
                request_type = "текстовый" if paid_request.request_type == 'text' else "с документами"
                
                await update.message.reply_text(
                    f"✅ Оплаченный вопрос сохранен!\n\n"
                    f"📋 У вас остался оплаченный {request_type} вопрос.\n"
                    f"Вы можете использовать его позже в меню 'Платные вопросы'.",
                    reply_markup=get_main_menu()
                )
            session.close()
        
        # Очищаем все состояния кроме информации об оплаченных вопросах
        keys_to_keep = []
        for key in list(context.user_data.keys()):
            if not key.startswith('paid_'):
                context.user_data[key] = None
                del context.user_data[key]

        await update.message.reply_text(
            "Действие отменено. Оплаченные вопросы сохранены для будущего использования.",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        # Игнорируем ошибку о запуске нескольких экземпляров
        if "Conflict: terminated by other getUpdates request" in str(context.error):
            logger.warning("Multiple bot instances detected, ignoring error")
            return
        
        logger.error(f"Update {update} caused error {context.error}\n{traceback.format_exc()}")

        try:
            # Удаляем временные файлы если есть
            if context.user_data and 'files' in context.user_data:
                for file_path in context.user_data['files']:
                    if os.path.exists(file_path):
                        os.remove(file_path)
        except:
            pass

        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    f"❌ Произошла ошибка:\n\n"
                    f"Детали: {str(context.error)[:500]}\n\n"
                    f"Пожалуйста, попробуйте снова или обратитесь в поддержку.",
                    reply_markup=get_main_menu()
                )
            except:
                pass

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка голосовых сообщений"""
        await update.message.reply_text(
            "🎤 Мы еще не умеем отвечать на голосовые сообщения.\n\n"
            "Пожалуйста, воспользуйтесь кнопками из меню или напишите текст.",
            reply_markup=get_main_menu()
        )

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка фотографий"""
        await update.message.reply_text(
            "📷 Фотографии не поддерживаются.\n\n"
            "Пожалуйста, отправьте файл в формате PDF, DOCX или TXT.",
            reply_markup=get_main_menu()
        )

    async def handle_unsupported_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка неподдерживаемых типов медиа"""
        await update.message.reply_text(
            "📁 Этот тип медиа не поддерживается.\n\n"
            "Пожалуйста, отправьте текстовое сообщение или файл в формате PDF, DOCX, TXT.",
            reply_markup=get_main_menu()
        )

    def setup_handlers(self):
        """Настройка обработчиков"""
        # Conversation handler для вопросов
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.handle_menu, pattern='^(free_text|free_file|paid_text|paid_file)$')
            ],
            states={
                WAITING_QUESTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_question),
                    CallbackQueryHandler(self.cancel, pattern='^main_menu$')
                ],
                WAITING_FILE_QUESTION: [
                    MessageHandler(filters.Document.ALL, self.handle_file),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_file_question),
                    CallbackQueryHandler(self.cancel, pattern='^main_menu$')
                ]
            },
            fallbacks=[
                CommandHandler('cancel', self.cancel),
                CallbackQueryHandler(self.cancel, pattern='^main_menu$')
            ],
            allow_reentry=True
        )

        # Регистрируем обработчики
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("menu", self.menu_command))
        self.application.add_handler(CallbackQueryHandler(self.handle_menu, pattern='^(?!free_text|free_file|paid_text|paid_file).*$'))
        self.application.add_handler(conv_handler)

        # Обработчики платежей
        self.application.add_handler(PreCheckoutQueryHandler(self.pre_checkout_callback))
        self.application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment_callback))

        # Обработчики медиа
        self.application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

        # Общий обработчик для других неподдерживаемых медиа
        unsupported_media_filters = (filters.VIDEO | filters.AUDIO |
                                   filters.VIDEO_NOTE | filters.ANIMATION)
        self.application.add_handler(MessageHandler(unsupported_media_filters, self.handle_unsupported_media))

        # Обработчик неожиданных текстовых сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_unexpected_text))

        # Обработчик ошибок
        self.application.add_error_handler(self.error_handler)

    async def handle_unexpected_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка неожиданных текстовых сообщений"""
        # Проверяем, не ожидаем ли мы вопрос после оплаты
        if context.user_data.get('paid_request_id') or context.user_data.get('question_type') in ['paid', 'subscription']:
            # Определяем тип вопроса
            waiting_for = context.user_data.get('waiting_for', 'text')
            
            if waiting_for == 'text':
                # Обрабатываем как текстовый вопрос
                await self.handle_text_question(update, context)
            elif waiting_for == 'file':
                # Обрабатываем как вопрос с файлами
                await self.handle_file_question(update, context)
            return
        
        # Если это не оплаченный вопрос, показываем меню
        await update.message.reply_text(
            "Пожалуйста, используйте меню для навигации:",
            reply_markup=get_main_menu()
        )

    async def set_bot_commands(self, application):
        """Установка команд бота"""
        commands = [
            BotCommand("start", "Запустить Скорую Юридическую"),
            BotCommand("menu", "Главное меню")
        ]
        await application.bot.set_my_commands(commands)

    def run(self):
        """Запуск бота"""
        # Создаем приложение с увеличенными таймаутами
        from telegram.ext import ApplicationBuilder
        
        self.application = ApplicationBuilder() \
            .token(BOT_TOKEN) \
            .read_timeout(30) \
            .write_timeout(30) \
            .connect_timeout(30) \
            .pool_timeout(30) \
            .build()

        # Настраиваем обработчики
        self.setup_handlers()

        # Устанавливаем команды бота
        self.application.post_init = self.set_bot_commands

        # Запускаем бота
        logger.info("Бот запущен...")
        try:
            self.application.run_polling(
                allowed_updates=Update.ALL_TYPES, 
                drop_pending_updates=True,
                close_loop=False
            )
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем.")
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")

def main():
    """Основная функция запуска"""
    bot = LegalBot()
    bot.run()

if __name__ == '__main__':
    main()