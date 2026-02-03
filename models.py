from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Система токенов
    free_requests_left = Column(Integer, default=4)

    # Подписка
    subscription_type = Column(String(50), default='none')  # 'none', '2weeks', '1month', '3months'
    subscription_end = Column(DateTime)

    # Отношения
    requests = relationship("UserRequest", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, user_id={self.user_id}, username={self.username})>"

class UserRequest(Base):
    __tablename__ = 'user_requests'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    timestamp = Column(DateTime, default=datetime.utcnow)
    question = Column(Text)
    answer = Column(Text)
    tokens_used = Column(Integer, default=0)
    has_files = Column(Boolean, default=False)
    files_info = Column(Text)

    # Отношения
    user = relationship("User", back_populates="requests")

    def __repr__(self):
        return f"<UserRequest(id={self.id}, user_id={self.user_id}, timestamp={self.timestamp})>"