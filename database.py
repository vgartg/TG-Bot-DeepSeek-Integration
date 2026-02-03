from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, User, UserRequest
from config import DATABASE_URL
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        try:
            connect_args = {}
            if DATABASE_URL.startswith('sqlite'):
                connect_args = {"check_same_thread": False}

            self.engine = create_engine(DATABASE_URL, connect_args=connect_args)
            self.SessionLocal = scoped_session(sessionmaker(bind=self.engine))
            Base.metadata.create_all(self.engine)
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def get_session(self):
        return self.SessionLocal()

    def get_or_create_user(self, session, user_id, username=None, first_name=None, last_name=None):
        try:
            user = session.query(User).filter(User.user_id == user_id).first()
            if not user:
                user = User(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    created_at=datetime.utcnow(),
                    free_requests_left=4,
                    subscription_type='none'
                )
                session.add(user)
                session.commit()
                logger.info(f"New user created: {user_id}")
            return user
        except Exception as e:
            session.rollback()
            logger.error(f"Error in get_or_create_user: {e}")
            raise

    def update_user_tokens(self, session, user_id, request_type='free'):
        try:
            user = session.query(User).filter(User.user_id == user_id).first()
            if not user:
                return False

            # Проверяем активную подписку
            has_subscription = False
            if user.subscription_type != 'none' and user.subscription_end:
                has_subscription = user.subscription_end > datetime.utcnow()

            if has_subscription:
                return True  # Подписка активна, списание не требуется

            if request_type == 'free':
                if user.free_requests_left > 0:
                    user.free_requests_left -= 1
                    session.commit()
                    return True
                return False
            else:
                # Для платных вопросов - всегда разрешаем, если есть подписка
                # или они покупаются через оплату
                return True
        except Exception as e:
            session.rollback()
            logger.error(f"Error in update_user_tokens: {e}")
            return False

    def add_request(self, session, user_id, question, answer, tokens_used=0, has_files=False, files_info=None):
        try:
            question_truncated = question[:1000] if question else ''
            answer_truncated = answer[:2000] if answer else ''

            request = UserRequest(
                user_id=user_id,
                question=question_truncated,
                answer=answer_truncated,
                tokens_used=tokens_used,
                has_files=has_files,
                files_info=files_info,
                timestamp=datetime.utcnow()
            )
            session.add(request)
            session.commit()
            logger.info(f"Request saved for user {user_id}, tokens: {tokens_used}")
            return request
        except Exception as e:
            session.rollback()
            logger.error(f"Error in add_request: {e}")
            return None

    def get_user_stats(self, session, user_id):
        try:
            user = session.query(User).filter(User.user_id == user_id).first()
            if not user:
                return None

            total_requests = session.query(UserRequest).filter(UserRequest.user_id == user_id).count()
            has_subscription = False
            subscription_info = None
            
            if user.subscription_type != 'none' and user.subscription_end:
                has_subscription = user.subscription_end > datetime.utcnow()
                if has_subscription:
                    subscription_info = {
                        'type': user.subscription_type,
                        'end': user.subscription_end
                    }

            return {
                'free_requests_left': user.free_requests_left,
                'has_subscription': has_subscription,
                'subscription_info': subscription_info,
                'total_requests': total_requests
            }
        except Exception as e:
            logger.error(f"Error in get_user_stats: {e}")
            return None

    def activate_subscription(self, session, user_id, subscription_type, duration_days):
        try:
            user = session.query(User).filter(User.user_id == user_id).first()
            if not user:
                return False

            user.subscription_type = subscription_type
            user.subscription_end = datetime.utcnow() + timedelta(days=duration_days)
            session.commit()
            logger.info(f"Subscription activated for user {user_id}: {subscription_type} for {duration_days} days")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Error in activate_subscription: {e}")
            return False

# Глобальный экземпляр базы данных
db = Database()