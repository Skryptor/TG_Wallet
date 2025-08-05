# init_db.py
from db import engine
from models import Base

if __name__ == '__main__':
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    print("База данных успешно пересоздана!")