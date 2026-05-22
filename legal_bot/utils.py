import os
import tempfile
import logging
from io import BytesIO

import qrcode
from PIL import Image

from .config import SUPPORTED_FILE_TYPES, MAX_TELEGRAM_MESSAGE_LENGTH

logger = logging.getLogger(__name__)

def generate_qr_code(url, bot=None):
    """Генерирует QR-код для ссылки.

    Параметр `bot` оставлен для обратной совместимости и не используется.
    """
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        bio = BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)

        return bio
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        return None

def format_answer(answer, max_length=MAX_TELEGRAM_MESSAGE_LENGTH):
    """Форматирует ответ для отправки в Telegram."""
    if len(answer) <= max_length:
        return [answer]

    parts = []
    while answer:
        if len(answer) <= max_length:
            parts.append(answer)
            break

        split_point = answer[:max_length].rfind('\n\n')
        if split_point == -1:
            split_point = answer[:max_length].rfind('. ')
            if split_point == -1:
                split_point = max_length

        parts.append(answer[:split_point + 1])
        answer = answer[split_point + 1:]

    return parts

def check_file_type(filename):
    """Проверяет поддерживаемый тип файла."""
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUPPORTED_FILE_TYPES

def get_file_size_mb(file_path):
    """Получает размер файла в МБ."""
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except OSError:
        return 0

def resize_image_if_needed(file_path, max_size_mb=10):
    """Изменяет размер изображения если оно слишком большое."""
    try:
        file_size_mb = get_file_size_mb(file_path)
        if file_size_mb <= max_size_mb:
            return file_path

        img = Image.open(file_path)

        max_dimension = 2000
        if img.width > max_dimension or img.height > max_dimension:
            ratio = min(max_dimension / img.width, max_dimension / img.height)
            new_width = int(img.width * ratio)
            new_height = int(img.height * ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            temp_path = tempfile.mktemp(suffix='.jpg')
            img.save(temp_path, 'JPEG', quality=85)

            return temp_path

        return file_path
    except Exception as e:
        logger.error(f"Error resizing image: {e}")
        return file_path
