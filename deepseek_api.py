import openai
from openai import OpenAI
import logging
from typing import List, Optional, Dict, Any
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL, SYSTEM_PROMPT
import base64
import mimetypes
import os

logger = logging.getLogger(__name__)

class DeepSeekAPI:
    def __init__(self):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_BASE
        )
        self.model = DEEPSEEK_MODEL

    def process_query(self, user_query: str, 
                     files: Optional[List[str]] = None,
                     use_search: bool = True,
                     use_deepthink: bool = True) -> dict:
        """Обрабатывает запрос пользователя"""
        try:
            # Формируем полное сообщение с system prompt
            full_message = f"{SYSTEM_PROMPT}\n\nОтветь на следующий вопрос: {user_query}"
            
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
                for file_path in files:
                    if os.path.exists(file_path):
                        mime_type = self.get_mime_type(file_path)
                        base64_data = self.file_to_base64(file_path)
                        
                        if mime_type.startswith('image/'):
                            # Для изображений
                            file_contents.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{base64_data}"
                                }
                            })
                        else:
                            # Для документов - пробуем читать как текст
                            try:
                                if file_path.lower().endswith('.txt'):
                                    with open(file_path, 'r', encoding='utf-8') as f:
                                        text_content = f.read()
                                    file_contents.append({
                                        "type": "text",
                                        "text": f"Содержимое файла {os.path.basename(file_path)}:\n{text_content}"
                                    })
                                else:
                                    # Для других форматов сообщаем о наличии файла
                                    file_contents.append({
                                        "type": "text",
                                        "text": f"Приложен файл: {os.path.basename(file_path)} (формат: {mime_type})"
                                    })
                            except Exception as file_error:
                                logger.error(f"Error reading file {file_path}: {file_error}")
                                file_contents.append({
                                    "type": "text",
                                    "text": f"Приложен файл: {os.path.basename(file_path)}"
                                })
                
                if file_contents:
                    # Добавляем текстовый запрос к файлам
                    file_contents.insert(0, {
                        "type": "text",
                        "text": full_message
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
            else:
                messages.append({
                    "role": "user",
                    "content": full_message
                })
            
            # Настраиваем параметры запроса
            # УБИРАЕМ web_search, так как DeepSeek API не поддерживает его напрямую
            # Вместо этого можно использовать информацию о поиске в промпте
            if use_search and (not files or len(files) == 0):
                # Добавляем инструкцию для поиска информации в промпт
                search_note = "\n\nПРИМЕЧАНИЕ: Если необходимо, используй актуальную информацию из интернета для ответа, основываясь на своем обучении."
                if len(messages) > 0 and messages[-1]["role"] == "user":
                    if isinstance(messages[-1]["content"], str):
                        messages[-1]["content"] += search_note
                    elif isinstance(messages[-1]["content"], list):
                        # Находим текстовую часть и добавляем примечание
                        for item in messages[-1]["content"]:
                            if item["type"] == "text":
                                item["text"] += search_note
                                break
            
            params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 4000,
                "temperature": 0.3,
            }
            
            logger.info(f"Sending request to DeepSeek with {len(messages)} messages")
            if files:
                logger.info(f"Files attached: {len(files)}")
            
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
            # Определяем по расширению
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