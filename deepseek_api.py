import openai
from openai import OpenAI
import logging
from typing import List, Optional, Dict, Any
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL, SYSTEM_PROMPT
import base64
import mimetypes
import os
import docx
import PyPDF2
import pdfplumber
from PIL import Image
import io

logger = logging.getLogger(__name__)

class DeepSeekAPI:
    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_BASE
        )
        self.model = DEEPSEEK_MODEL

    def extract_text_from_file(self, file_path: str) -> str:
        """Извлекает текст из файла (PDF, DOCX, TXT)"""
        try:
            ext = os.path.splitext(file_path)[1].lower()

            if ext == '.txt':
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()

            elif ext == '.docx':
                doc = docx.Document(file_path)
                text = []
                for paragraph in doc.paragraphs:
                    if paragraph.text.strip():
                        text.append(paragraph.text)
                return '\n'.join(text)

            elif ext == '.pdf':
                text = []
                try:
                    with pdfplumber.open(file_path) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text.append(page_text)
                except:
                    with open(file_path, 'rb') as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        for page in pdf_reader.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text.append(page_text)
                return '\n'.join(text)
            else:
                return ""

        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
            return ""

    def process_query(self, user_query: str,
                     files: Optional[List[str]] = None,
                     use_search: bool = True,
                     use_deepthink: bool = True) -> dict:
        """Обрабатывает запрос пользователя"""
        try:
            # Формируем полное сообщение
            full_message = f"{SYSTEM_PROMPT}\n\nВопрос пользователя: {user_query}"

            # Подготавливаем сообщения
            messages = []

            # Добавляем deepthink если нужно
            if use_deepthink:
                messages.append({
                    "role": "system",
                    "content": "Пожалуйста, используй режим deepthink для глубокого анализа. Отвечай на русском языке."
                })

            # Основное сообщение
            message_content = full_message

            # Добавляем файлы если есть
            if files and len(files) > 0:
                file_contents = []

                # Добавляем текстовую часть запроса
                file_contents.append({
                    "type": "text",
                    "text": full_message
                })

                for file_path in files:
                    if os.path.exists(file_path):
                        mime_type = self.get_mime_type(file_path)
                        file_name = os.path.basename(file_path)

                        if mime_type.startswith('image/'):
                            # Для изображений используем vision API
                            try:
                                with Image.open(file_path) as img:
                                    if img.mode != 'RGB':
                                        img = img.convert('RGB')
                                    
                                    buffer = io.BytesIO()
                                    img.save(buffer, format='JPEG', quality=85)
                                    buffer.seek(0)
                                    
                                    base64_data = base64.b64encode(buffer.read()).decode('utf-8')
                                    
                                    file_contents.append({
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{base64_data}"
                                        }
                                    })
                            except Exception as img_error:
                                logger.error(f"Error processing image {file_path}: {img_error}")
                                file_contents.append({
                                    "type": "text",
                                    "text": f"Файл '{file_name}' (изображение) - не удалось обработать"
                                })
                        else:
                            # Для документов извлекаем текст
                            text_content = self.extract_text_from_file(file_path)
                            if text_content:
                                max_text_length = 15000
                                if len(text_content) > max_text_length:
                                    text_content = text_content[:max_text_length] + "... [текст сокращен]"

                                file_contents.append({
                                    "type": "text",
                                    "text": f"Содержимое файла '{file_name}':\n{text_content}"
                                })
                            else:
                                file_contents.append({
                                    "type": "text",
                                    "text": f"Файл '{file_name}' (формат: {mime_type}) - не удалось извлечь текст"
                                })

                messages.append({
                    "role": "user",
                    "content": file_contents
                })

            else:
                messages.append({
                    "role": "user",
                    "content": full_message
                })

            # Настраиваем параметры запроса
            params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 4000,
                "temperature": 0.3,
            }

            # Добавляем инструкцию для поиска если нужно
            if use_search:
                for msg in messages:
                    if msg["role"] == "user":
                        if isinstance(msg["content"], str):
                            msg["content"] += "\n\nИспользуй актуальную информацию из интернета для ответа, если это необходимо."
                        elif isinstance(msg["content"], list):
                            for item in msg["content"]:
                                if item["type"] == "text":
                                    item["text"] += "\n\nИспользуй актуальную информацию из интернета для ответа, если это необходимо."
                                    break

            logger.info(f"Отправка запроса в DeepSeek с {len(messages)} сообщениями, search={use_search}, deepthink={use_deepthink}")
            if files:
                logger.info(f"Прикреплено файлов: {len(files)}")

            # Отправляем запрос
            response = self.client.chat.completions.create(**params)

            # Получаем ответ
            answer = response.choices[0].message.content

            # Оцениваем использование токенов
            tokens_used = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else len(answer) // 4

            return {
                "answer": answer,
                "tokens_used": tokens_used,
                "has_files": bool(files and len(files) > 0)
            }

        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            return {"error": f"Ошибка при обработке запроса: {str(e)}"}

    def process_query_with_files(self, user_query: str,
                                files: Optional[List[str]] = None,
                                use_search: bool = False,  # Для анализа файлов поиск ВЫКЛЮЧЕН
                                use_deepthink: bool = True) -> dict:
        """Обрабатывает запрос с файлами (только для анализа файлов, без поиска)"""
        try:
            # Специальный промпт для анализа файлов
            analysis_prompt = """Ты юрист с 30-летним стажем. Проанализируй предоставленные документы и выдели ключевую информацию.
            Обрати внимание на:
            1. Имена и фамилии людей
            2. Даты и сроки
            3. Суммы денег
            4. Адреса и места
            5. Номера договоров, счетов, документов
            6. Юридические термины и формулировки
            7. Обязательства сторон
            8. Условия и ограничения

            Представь краткий анализ каждого документа, выдели самую важную информацию."""

            full_message = f"{analysis_prompt}\n\nЗадача: {user_query}"

            # Подготавливаем сообщения
            messages = []

            # Добавляем deepthink если нужно
            if use_deepthink:
                messages.append({
                    "role": "system",
                    "content": "Пожалуйста, внимательно проанализируй документы. Отвечай на русском языке."
                })

            # Добавляем файлы если есть
            if files and len(files) > 0:
                file_contents = []

                # Добавляем текстовую часть запроса
                file_contents.append({
                    "type": "text",
                    "text": full_message
                })

                for file_path in files:
                    if os.path.exists(file_path):
                        mime_type = self.get_mime_type(file_path)
                        file_name = os.path.basename(file_path)

                        if mime_type.startswith('image/'):
                            # Для изображений используем vision API
                            try:
                                with Image.open(file_path) as img:
                                    if img.mode != 'RGB':
                                        img = img.convert('RGB')
                                    
                                    buffer = io.BytesIO()
                                    img.save(buffer, format='JPEG', quality=85)
                                    buffer.seek(0)
                                    
                                    base64_data = base64.b64encode(buffer.read()).decode('utf-8')
                                    
                                    file_contents.append({
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{base64_data}"
                                        }
                                    })
                            except Exception as img_error:
                                logger.error(f"Error processing image {file_path}: {img_error}")
                                file_contents.append({
                                    "type": "text",
                                    "text": f"Файл '{file_name}' (изображение) - не удалось обработать"
                                })
                        else:
                            # Для документов извлекаем текст
                            text_content = self.extract_text_from_file(file_path)
                            if text_content:
                                max_text_length = 15000
                                if len(text_content) > max_text_length:
                                    text_content = text_content[:max_text_length] + "... [текст сокращен]"

                                file_contents.append({
                                    "type": "text",
                                    "text": f"Содержимое файла '{file_name}':\n{text_content}"
                                })
                            else:
                                file_contents.append({
                                    "type": "text",
                                    "text": f"Файл '{file_name}' (формат: {mime_type})"
                                })

                messages.append({
                    "role": "user",
                    "content": file_contents
                })

            else:
                messages.append({
                    "role": "user",
                    "content": full_message
                })

            # Настраиваем параметры запроса - поиск ВЫКЛЮЧЕН для анализа файлов
            params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 2000,
                "temperature": 0.2,
            }

            logger.info(f"Отправка запроса анализа файлов в DeepSeek с {len(files)} файлами, search={use_search}, deepthink={use_deepthink}")

            # Отправляем запрос
            response = self.client.chat.completions.create(**params)

            # Получаем ответ
            answer = response.choices[0].message.content

            # Оцениваем использование токенов
            tokens_used = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else len(answer) // 4

            return {
                "answer": answer,
                "tokens_used": tokens_used,
                "has_files": bool(files and len(files) > 0)
            }

        except Exception as e:
            logger.error(f"Error processing file query: {e}", exc_info=True)
            return {"error": f"Ошибка при анализе файлов: {str(e)}"}

    def file_to_base64(self, file_path: str) -> str:
        """Конвертирует файл в base64 строку"""
        try:
            with open(file_path, "rb") as file:
                return base64.b64encode(file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error converting file to base64: {e}")
            return ""

    def get_mime_type(self, file_path: str) -> str:
        """Определяет MIME тип файла"""
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.pdf':
                return 'application/pdf'
            elif ext == '.docx':
                return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            elif ext == '.txt':
                return 'text/plain'
            elif ext in ['.jpg', '.jpeg']:
                return 'image/jpeg'
            elif ext == '.png':
                return 'image/png'
            else:
                return 'application/octet-stream'
        return mime_type

# Глобальный экземпляр API
deepseek_api = DeepSeekAPI()