import os
import tempfile
import qrcode
from io import BytesIO
import logging

logger = logging.getLogger(__name__)

def save_telegram_file(file, file_name):
    """Сохраняет файл из Telegram во временную папку"""
    try:
        # Создаем временный файл
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, file_name)

        # Скачиваем файл
        file.download(file_path)

        logger.info(f"File saved to: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        return None

def generate_qr_code(url, bot):
    """Генерирует QR-код для ссылки"""
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

        # Сохраняем в BytesIO
        bio = BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)

        return bio
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        return None

def format_answer(answer, max_length=4096):
    """Форматирует ответ для отправки в Telegram"""
    # Telegram имеет ограничение на длину сообщения
    if len(answer) <= max_length:
        return [answer]

    # Разбиваем на части
    parts = []
    while answer:
        if len(answer) <= max_length:
            parts.append(answer)
            break

        # Ищем точку разрыва
        split_point = answer[:max_length].rfind('\n\n')
        if split_point == -1:
            split_point = answer[:max_length].rfind('. ')
            if split_point == -1:
                split_point = max_length

        parts.append(answer[:split_point + 1])
        answer = answer[split_point + 1:]

    return parts

def check_file_type(filename):
    """Проверяет поддерживаемый тип файла"""
    from config import SUPPORTED_FILE_TYPES
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUPPORTED_FILE_TYPES

def get_file_size_mb(file_path):
    """Получает размер файла в МБ"""
    try:
        return os.path.getsize(file_path) / (1024 * 1024)
    except:
        return 0