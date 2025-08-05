from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

# Исправленный путь к базе данных
engine = create_engine("sqlite:///finance_bot.db", echo=False)

# Создание таблиц при первом запуске
Base.metadata.create_all(engine)

# Создание фабрики сессий
SessionLocal = sessionmaker(bind=engine)

def get_session():
    """Генератор сессий для использования в контекстных менеджерах"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()