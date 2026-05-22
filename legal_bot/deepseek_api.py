import logging
import os
import mimetypes
from typing import List, Optional, Dict

import docx
import PyPDF2
import pdfplumber
import requests
from openai import OpenAI

from .config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class DeepSeekAPI:
    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_BASE,
            timeout=60.0
        )

        self.api_key = DEEPSEEK_API_KEY
        self.model = DEEPSEEK_MODEL
        self.base_url = DEEPSEEK_API_BASE

    def get_mime_type(self, file_path: str) -> str:
        """Определяет MIME тип файла"""
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.pdf':
                return 'application/pdf'
            elif ext == '.docx':
                return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            elif ext == '.txt':
                return 'text/plain'
            else:
                return 'application/octet-stream'
        return mime_type

    def upload_file_to_deepseek(self, file_path: str) -> Optional[str]:
        """Загружает файл в DeepSeek API и возвращает file_id."""
        try:
            upload_url = f"{self.base_url}/files"

            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Accept': 'application/json'
            }

            mime_type = self.get_mime_type(file_path)
            file_name = os.path.basename(file_path)

            with open(file_path, 'rb') as file_content:
                files = {
                    'file': (file_name, file_content, mime_type)
                }

                response = requests.post(upload_url, headers=headers, files=files, timeout=60)

            if response.status_code == 200:
                result = response.json()
                file_id = result.get('id')
                logger.info(f"Файл успешно загружен в DeepSeek, file_id: {file_id}")
                return file_id
            else:
                logger.error(f"Ошибка загрузки файла: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Exception in upload_file_to_deepseek: {e}")
            return None

    def extract_text_from_file(self, file_path: str) -> tuple[str, bool]:
        """Извлекает текст из файла локально (резервный метод)."""
        try:
            ext = os.path.splitext(file_path)[1].lower()

            if ext == '.txt':
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                success = len(text.strip()) > 0
                return text, success

            elif ext == '.docx':
                doc = docx.Document(file_path)
                text = []
                for paragraph in doc.paragraphs:
                    if paragraph.text.strip():
                        text.append(paragraph.text)
                result = '\n'.join(text)
                success = len(result.strip()) > 0
                return result, success

            elif ext == '.pdf':
                text = []
                try:
                    with pdfplumber.open(file_path) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text.append(page_text)
                except Exception:
                    with open(file_path, 'rb') as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        for page in pdf_reader.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text.append(page_text)
                result = '\n'.join(text)
                success = len(result.strip()) > 0
                return result, success
            else:
                return "", False

        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
            return f"Ошибка при извлечении текста: {str(e)[:200]}", False

    def process_query(self, user_query: str,
                     file_texts: Optional[List[Dict]] = None,
                     use_search: bool = False,
                     use_deepthink: bool = True) -> dict:
        """Основная точка входа для обработки запросов."""
        try:
            if file_texts and len(file_texts) > 0:
                files_content = ""
                for file_data in file_texts:
                    filename = file_data.get('filename', 'file')
                    text = file_data.get('text', '')
                    files_content += f"\n\n=== ФАЙЛ: {filename} ===\n{text}"

                full_query = f"""{SYSTEM_PROMPT}

ДОКУМЕНТЫ ДЛЯ АНАЛИЗА:{files_content}

ВОПРОС: {user_query}

Проанализируйте предоставленные документы и дайте юридически обоснованный ответ на вопрос пользователя."""
            else:
                full_query = f"{SYSTEM_PROMPT}\n\nВопрос пользователя: {user_query}"

            messages = []

            if use_deepthink:
                messages.append({
                    "role": "system",
                    "content": "Пожалуйста, используй режим deepthink для глубокого анализа. Отвечай на русском языке."
                })

            messages.append({
                "role": "user",
                "content": full_query
            })

            if use_search:
                for msg in messages:
                    if msg["role"] == "user" and isinstance(msg["content"], str):
                        msg["content"] += "\n\nИспользуй актуальную информацию из интернета для ответа, если это необходимо."

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=4000,
                temperature=0.3,
                timeout=45.0
            )

            answer = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else len(answer) // 4

            return {
                "answer": answer,
                "tokens_used": tokens_used,
                "has_files": bool(file_texts and len(file_texts) > 0)
            }

        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            return {"error": f"Ошибка при обработке запроса: {str(e)}"}


deepseek_api = DeepSeekAPI()
