import logging
from telegram import Update, BotCommand, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
    PreCheckoutQueryHandler
)
from telegram.error import BadRequest, TimedOut
import os
from datetime import datetime, timedelta
import traceback
import json
import tempfile

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
                # Просто отвечаем на callback_query и отправляем новое сообщение
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
        session.close()

        # Отправляем приветственное сообщение
        if update.message:
            await update.message.reply_text(
                "Добро пожаловать в Скорую Юридическую Помощь!",
                reply_markup=get_main_menu()
            )
        else:
            await update.callback_query.message.reply_text(
                "Добро пожаловать в Скорую Юридическую Помощь!",
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
            await self.safe_edit_message(
                query,
                "Выберите тип платного вопроса:\n\n"
                "📝 Ответ на вопрос - 100 руб.\n"
                "📎 Ответ с загрузкой документов - 200 руб.\n\n"
                "После оплаты вы сможете сразу задать вопрос.",
                reply_markup=get_paid_questions_menu()
            )

        elif query.data == 'menu_subscription':
            await self.safe_edit_message(
                query,
                "Выберите вариант подписки:\n\n"
                "🔄 Безлимит на 2 недели - 1000 руб.\n"
                "🔄 Безлимит на 1 месяц - 1500 руб.\n"
                "🔄 Безлимит на 3 месяца - 3000 руб.\n\n"
                "Подписка дает неограниченное количество запросов.",
                reply_markup=get_subscription_menu()
            )

        elif query.data.startswith('sub_'):
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

            # Создаем provider_data для чека (требование 54-ФЗ)
            provider_data = {
                "receipt": {
                    "items": [
                        {
                            "description": description[:128],  # Максимум 128 символов
                            "quantity": "1.00",
                            "amount": {
                                "value": f"{price / 100:.2f}",
                                "currency": CURRENCY
                            },
                            "vat_code": 1  # Ставка НДС для самозанятых
                        }
                    ]
                }
            }

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
                    send_phone_number_to_provider=True,
                    provider_data=json.dumps(provider_data)
                )

                # Отправляем сообщение с инструкцией для тестового режима
                if PROVIDER_TOKEN.split(':')[1] == 'TEST':
                    await query.message.reply_text(
                        "💳 Для оплаты используйте тестовые данные карты:\n"
                        "Номер: 1111 1111 1111 1026\n"
                        "Срок: 12/22\n"
                        "CVC: 000"
                    )

            except Exception as e:
                logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                await query.message.reply_text(
                    "❌ Оплата временно не доступна. Пожалуйста, попробуйте позже."
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
                "Поделиться ботом с друзьями:",
                reply_markup=get_share_initial_menu()
            )

        elif query.data == 'share_link':
            bot_username = context.bot.username
            share_url = f"https://t.me/{bot_username}"
            await self.safe_edit_message(
                query,
                f"Приглашайте друзей!\n\n"
                f"Ссылка на бота: {share_url}\n\n"
                f"Просто отправьте эту ссылку или нажмите на нее.",
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
                    "🔘 Режим deepthink включен, ответ может занять до 1-2 минут.\n"
                    "🔘 Ответ будет сформирован с учетом актуального законодательства РФ.\n"
                    "🔘 Поиск в интернете доступен через встроенные знания модели.",
                    reply_markup=get_cancel_button()
                )
                return WAITING_QUESTION

            else:
                # Платный вопрос - отправляем счет
                payload = 'question_text'
                title = "Ответ на юридический вопрос"
                description = "Ответ на один юридический вопрос без документов"
                price = PRICES['question_text']
                prices = [LabeledPrice("Ответ на вопрос", price)]

                # Создаем provider_data для чека
                provider_data = {
                    "receipt": {
                        "items": [
                            {
                                "description": description[:128],
                                "quantity": "1.00",
                                "amount": {
                                    "value": f"{price / 100:.2f}",
                                    "currency": CURRENCY
                                },
                                "vat_code": 1
                            }
                        ]
                    }
                }

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
                        send_phone_number_to_provider=True,
                        provider_data=json.dumps(provider_data)
                    )

                    # Инструкция для тестового режима
                    if PROVIDER_TOKEN.split(':')[1] == 'TEST':
                        await query.message.reply_text(
                            "💳 Для оплаты используйте тестовые данные карты:\n"
                            "Номер: 1111 1111 1111 1026\n"
                            "Срок: 12/22\n"
                            "CVC: 000"
                        )

                except Exception as e:
                    logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                    await query.message.reply_text(
                        "❌ Оплата временно не доступна. Пожалуйста, попробуйте позже.",
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
                    "📎 Отправьте файл (PDF, DOCX, TXT, JPG, PNG) и ваш вопрос:\n\n"
                    "🔘 Максимальный размер файла: 20 МБ\n"
                    "🔘 При загрузке файлов поиск в интернете отключается\n"
                    "🔘 Можно отправить несколько файлов, затем написать вопрос",
                    reply_markup=get_cancel_button()
                )
                return WAITING_FILE_QUESTION

            else:
                # Платный вопрос с файлами - отправляем счет
                payload = 'question_file'
                title = "Ответ с анализом документов"
                description = "Ответ на один юридический вопрос с анализом документов"
                price = PRICES['question_file']
                prices = [LabeledPrice("Ответ с документами", price)]

                # Создаем provider_data для чека
                provider_data = {
                    "receipt": {
                        "items": [
                            {
                                "description": description[:128],
                                "quantity": "1.00",
                                "amount": {
                                    "value": f"{price / 100:.2f}",
                                    "currency": CURRENCY
                                },
                                "vat_code": 1
                            }
                        ]
                    }
                }

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
                        send_phone_number_to_provider=True,
                        provider_data=json.dumps(provider_data)
                    )

                    # Инструкция для тестового режима
                    if PROVIDER_TOKEN.split(':')[1] == 'TEST':
                        await query.message.reply_text(
                            "💳 Для оплаты используйте тестовые данные карты:\n"
                            "Номер: 1111 1111 1111 1026\n"
                            "Срок: 12/22\n"
                            "CVC: 000"
                        )

                except Exception as e:
                    logger.error(f"Error sending invoice: {e}\n{traceback.format_exc()}")
                    await query.message.reply_text(
                        "❌ Оплата временно не доступна. Пожалуйста, попробуйте позже.",
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
                        f"📅 Срок действия: {duration_text}\n"
                        f"💰 Сумма оплаты: {payment.total_amount / 100} {payment.currency}\n\n"
                        f"Выберите действие:",
                        reply_markup=get_main_menu()
                    )
                else:
                    await update.message.reply_text(
                        "❌ Ошибка при активации подписки. Пожалуйста, обратитесь в поддержку.",
                        reply_markup=get_main_menu()
                    )

            elif payload in ['question_text', 'question_file']:
                # Оплата вопроса - переходим к ожиданию вопроса
                if payload == 'question_text':
                    context.user_data['question_type'] = 'paid'
                    context.user_data['waiting_for'] = 'text'

                    await update.message.reply_text(
                        f"✅ Оплата прошла успешно!\n\n"
                        f"💰 Сумма: {payment.total_amount / 100} {payment.currency}\n"
                        f"📝 Теперь напишите ваш юридический вопрос:\n\n"
                        f"🔘 Режим deepthink включен, ответ может занять до 1-2 минут.",
                        reply_markup=get_cancel_button()
                    )
                    return WAITING_QUESTION

                elif payload == 'question_file':
                    context.user_data['question_type'] = 'paid'
                    context.user_data['waiting_for'] = 'file'
                    context.user_data['files'] = []
                    context.user_data['file_context'] = []  # Для хранения контекста анализа файлов

                    await update.message.reply_text(
                        f"✅ Оплата прошла успешно!\n\n"
                        f"💰 Сумма: {payment.total_amount / 100} {payment.currency}\n"
                        f"📎 Теперь отправьте файл (PDF, DOCX, TXT, JPG, PNG) и ваш вопрос:\n\n"
                        f"🔘 Максимальный размер файла: 20 МБ\n"
                        f"🔘 Можно отправить несколько файлов, затем написать вопрос",
                        reply_markup=get_cancel_button()
                    )
                    return WAITING_FILE_QUESTION

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

        processing_msg = await update.message.reply_text(
            "🔄 Обрабатываю ваш вопрос...\n"
            "Это может занять до 1-2 минут (режим deepthink включен)."
        )

        try:
            # Отправляем запрос в DeepSeek
            result = deepseek_api.process_query(
                user_query=question_text,
                use_search=True,
                use_deepthink=True
            )

            if 'error' in result:
                await processing_msg.edit_text(f"❌ Ошибка: {result['error']}")
                session.close()
                return ConversationHandler.END

            # Сохраняем запрос в БД
            db.add_request(
                session,
                user_id,
                question_text,
                result['answer'],
                result['tokens_used'],
                False
            )

            # Списываем токен если нет подписки
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

            if has_subscription:
                await update.message.reply_text(
                    f"✅ Ответ сформирован!\n\n"
                    f"📊 Статистика:\n"
                    f"• Использовано токенов: {result['tokens_used']}\n"
                    f"• У вас активна подписка\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )
            else:
                await update.message.reply_text(
                    f"✅ Ответ сформирован!\n\n"
                    f"📊 Статистика:\n"
                    f"• Бесплатных вопросов осталось: {free_left}\n"
                    f"• Использовано токенов: {result['tokens_used']}\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )

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
        if 'files' not in context.user_data:
            context.user_data['files'] = []
        if 'file_context' not in context.user_data:
            context.user_data['file_context'] = []

        file = None
        file_id = None
        file_name = ""

        if update.message.document:
            file = update.message.document
            file_id = file.file_id
            file_name = file.file_name
        elif update.message.photo:
            file = update.message.photo[-1]
            file_id = file.file_id
            file_name = "photo.jpg"

        if not file:
            await update.message.reply_text("Пожалуйста, отправьте файл (PDF, DOCX, TXT, JPG, PNG)")
            return WAITING_FILE_QUESTION

        # Проверяем тип файла
        if not check_file_type(file_name):
            await update.message.reply_text(
                "📛 Неподдерживаемый тип файла.\n"
                "Поддерживаемые форматы: PDF, DOCX, TXT, JPG, PNG"
            )
            return WAITING_FILE_QUESTION

        try:
            # Скачиваем файл
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, file_name)

            # Получаем объект файла и скачиваем
            tg_file = await context.bot.get_file(file_id)
            await tg_file.download_to_drive(file_path)

            # Проверяем размер
            file_size_mb = get_file_size_mb(file_path)
            if file_size_mb > 20:
                await update.message.reply_text("📛 Файл слишком большой (максимум 20 МБ)")
                os.remove(file_path)
                return WAITING_FILE_QUESTION

            context.user_data['files'].append(file_path)

            # Анализируем файл и сохраняем контекст
            analysis_msg = await update.message.reply_text(
                f"🔄 Анализирую файл '{file_name}'...\n"
                f"Это может занять некоторое время в зависимости от размера файла."
            )

            # Шаг 1: Анализ файла
            analysis_result = deepseek_api.process_query_with_files(
                user_query=f"Проанализируй содержимое файла '{file_name}' и выдели ключевую информацию. "
                        f"Обрати внимание на имена, фамилии, даты, суммы, адреса и другие важные детали.",
                files=[file_path],
                use_search=False,  # Отключаем поиск для анализа файла
                use_deepthink=True
            )

            if 'error' in analysis_result:
                await analysis_msg.edit_text(f"📛 Ошибка при анализе файла: {analysis_result['error']}")
                # Удаляем временный файл
                if os.path.exists(file_path):
                    os.remove(file_path)
                return WAITING_FILE_QUESTION

            # Сохраняем контекст анализа
            context.user_data['file_context'].append({
                'filename': file_name,
                'analysis': analysis_result['answer'],
                'tokens': analysis_result['tokens_used']
            })

            await analysis_msg.edit_text(
                f"✅ Файл '{file_name}' проанализирован\n"
                f"Загружено файлов: {len(context.user_data['files'])}\n\n"
                "Теперь напишите ваш вопрос к этим документам:"
            )

            return WAITING_FILE_QUESTION

        except Exception as e:
            logger.error(f"Error downloading or analyzing file: {e}\n{traceback.format_exc()}")
            await update.message.reply_text("📛 Ошибка при загрузке или анализе файла")
            return WAITING_FILE_QUESTION

    async def handle_file_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка вопроса по файлам"""
        user_id = update.message.from_user.id
        question_text = update.message.text

        if 'files' not in context.user_data or not context.user_data['files']:
            await update.message.reply_text("Сначала загрузите файлы, затем задайте вопрос")
            return WAITING_FILE_QUESTION

        # Проверяем доступ
        session = db.get_session()
        user_stats = db.get_user_stats(session, user_id)

        question_type = context.user_data.get('question_type', 'free')
        has_subscription = user_stats['has_subscription'] if user_stats else False

        if not has_subscription:
            if question_type == 'free':
                if user_stats and user_stats['free_requests_left'] <= 0:
                    await update.message.reply_text(
                        "📛 У вас закончились бесплатные вопросы.\n\n"
                        "Перейдите в раздел 'Платные вопросы' или 'Подписка на безлимит'.",
                        reply_markup=get_main_menu()
                    )
                    # Удаляем временные файлы
                    for file_path in context.user_data['files']:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    session.close()
                    return ConversationHandler.END

        processing_msg = await update.message.reply_text(
            "🔄 Анализирую документы и обрабатываю вопрос...\n"
            "Это может занять несколько минут."
        )

        try:
            # Подготавливаем контекст из анализа файлов
            file_context = ""
            total_analysis_tokens = 0
            for file_data in context.user_data.get('file_context', []):
                file_context += f"\n\nАнализ файла '{file_data['filename']}':\n{file_data['analysis']}"
                total_analysis_tokens += file_data['tokens']

            # Формируем полный запрос с учетом ограничения Telegram на длину сообщения (4096 символов)
            if file_context:
                # Ограничиваем общую длину контекста, чтобы не превысить лимиты API
                max_context_length = 8000  # Оставляем место для вопроса и system prompt
                if len(file_context) > max_context_length:
                    file_context = file_context[:max_context_length] + "... [контекст сокращен]"

                # Добавляем инструкцию для модели
                instruction = "ИСПОЛЬЗУЙ ТОЛЬКО ИНФОРМАЦИЮ ИЗ ПРЕДОСТАВЛЕННЫХ ДОКУМЕНТОВ. Если ответа нет в документах, так и скажи.\n\n"
                full_query = f"{instruction}Контекст из проанализированных документов:{file_context}\n\nВопрос пользователя: {question_text}"
            else:
                full_query = question_text

            # Шаг 2: Отправляем вопрос с поиском, используя контекст анализа файлов
            result = deepseek_api.process_query(
                user_query=full_query,
                files=None,  # Файлы уже проанализированы, отправляем только текст
                use_search=True,  # Включаем поиск для ответа на вопрос
                use_deepthink=True
            )

            # Удаляем временные файлы
            for file_path in context.user_data['files']:
                if os.path.exists(file_path):
                    os.remove(file_path)

            if 'error' in result:
                await processing_msg.edit_text(f"📛 Ошибка: {result['error']}")
                session.close()
                return ConversationHandler.END

            # Сохраняем запрос в БД
            files_info = str(len(context.user_data['files'])) + " файлов"
            total_tokens = total_analysis_tokens + result['tokens_used']
            db.add_request(
                session,
                user_id,
                question_text,
                result['answer'],
                total_tokens,
                True,
                files_info
            )

            # Списываем токен если нет подписки
            if not has_subscription and question_type == 'free':
                db.update_user_tokens(session, user_id, 'free')

            session.close()

            # Отправляем ответ частями с учетом ограничения Telegram (4096 символов)
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

            if has_subscription:
                await update.message.reply_text(
                    f"✅ Анализ документов завершен!\n\n"
                    f"📊 Статистика:\n"
                    f"• Проанализировано файлов: {len(context.user_data['files'])}\n"
                    f"• Использовано токенов: {total_tokens}\n"
                    f"• У вас активна подписка\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )
            else:
                await update.message.reply_text(
                    f"✅ Анализ документов завершен!\n\n"
                    f"📊 Статистика:\n"
                    f"• Проанализировано файлов: {len(context.user_data['files'])}\n"
                    f"• Бесплатных вопросов осталось: {free_left}\n"
                    f"• Использовано токенов: {total_tokens}\n\n"
                    f"Выберите дальнейшее действие:",
                    reply_markup=get_main_menu()
                )

        except Exception as e:
            logger.error(f"Error processing file question: {e}\n{traceback.format_exc()}")
            # Удаляем временные файлы при ошибке
            for file_path in context.user_data.get('files', []):
                if os.path.exists(file_path):
                    os.remove(file_path)

            try:
                await processing_msg.edit_text(
                    f"📛 Произошла ошибка при анализе документов:\n\n"
                    f"Детали ошибки: {str(e)[:500]}\n\n"
                    f"Пожалуйста, попробуйте позже или обратитесь в поддержку."
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

        await update.message.reply_text(
            "Действие отменено.",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
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

    def setup_handlers(self):
        """Настройка обработчиков"""
        # Conversation handler для вопросов
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.handle_menu, pattern='^(free_text|free_file)$')
            ],
            states={
                WAITING_QUESTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_question),
                    CallbackQueryHandler(self.cancel, pattern='^main_menu$')
                ],
                WAITING_FILE_QUESTION: [
                    MessageHandler(filters.Document.ALL | filters.PHOTO, self.handle_file),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_file_question),
                    CallbackQueryHandler(self.cancel, pattern='^main_menu$')
                ]
            },
            fallbacks=[
                CommandHandler('cancel', self.cancel),
                CallbackQueryHandler(self.cancel, pattern='^main_menu$')
            ]
        )

        # Регистрируем обработчики
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CallbackQueryHandler(self.handle_menu, pattern='^(?!free_text|free_file).*$'))
        self.application.add_handler(conv_handler)

        # Обработчики платежей
        self.application.add_handler(PreCheckoutQueryHandler(self.pre_checkout_callback))
        self.application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment_callback))

        # Обработчик неожиданных текстовых сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_unexpected_text))

        # Обработчик ошибок
        self.application.add_error_handler(self.error_handler)

    async def handle_unexpected_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка неожиданных текстовых сообщений"""
        await update.message.reply_text(
            "Пожалуйста, используйте меню для навигации:",
            reply_markup=get_main_menu()
        )

    async def set_bot_commands(self, application):
        """Установка команд бота"""
        commands = [
            BotCommand("start", "Запустить бота"),
            BotCommand("menu", "Главное меню")
        ]
        await application.bot.set_my_commands(commands)

    def run(self):
        """Запуск бота"""
        # Создаем приложение
        self.application = Application.builder().token(BOT_TOKEN).build()

        # Настраиваем обработчики
        self.setup_handlers()

        # Устанавливаем команды бота
        self.application.post_init = self.set_bot_commands

        # Запускаем бота
        logger.info("Бот запущен...")
        try:
            self.application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
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