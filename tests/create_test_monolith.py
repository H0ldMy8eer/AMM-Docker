import os

def create_dummy_project():
    # Название папки, которая появится
    base_dir = "test_monolith_shop"
    
    # Здесь мы описываем структуру будущего монолита:
    # Ключ - это имя файла, Значение - это код внутри файла
    structure = {
        # Главный файл запуска
        "app.py": """
from flask import Flask
from users.views import user_bp
from products.views import product_bp

app = Flask(__name__)
app.register_blueprint(user_bp, url_prefix='/users')
app.register_blueprint(product_bp, url_prefix='/products')

if __name__ == '__main__':
    app.run(debug=True)
""",
        # Глобальные зависимости всего проекта
        "requirements.txt": """
Flask==3.0.0
requests==2.31.0
psycopg2-binary==2.9.9
""",
        # Модуль пользователей (будущий микросервис 1)
        # Импортирует: common → ребро users→common
        "users/": {
            "__init__.py": "",
            "views.py": """
from flask import Blueprint
from common import db

user_bp = Blueprint('users', __name__)

@user_bp.route('/')
def index():
    return "User List"
""",
            "models.py": """
from common import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
""",
        },
        # Модуль товаров (будущий микросервис 2)
        # Импортирует: common + users → рёбра products→common, products→users
        "products/": {
            "__init__.py": "",
            "views.py": """
from flask import Blueprint
from common import db
from users import models as user_models

product_bp = Blueprint('products', __name__)

@product_bp.route('/')
def list():
    return "Product List"
""",
            "utils.py": "import math\n# Вспомогательные функции",
        },
        # Модуль заказов (будущий микросервис 3)
        # Импортирует: common + users → рёбра orders→common, orders→users
        "orders/": {
            "__init__.py": "",
            "views.py": """
from flask import Blueprint
from common import db
from users import models as user_models

order_bp = Blueprint('orders', __name__)

@order_bp.route('/')
def list():
    return "Order List"
""",
            # У заказов есть СВОЯ уникальная библиотека, которой нет в общем файле
            "requirements.txt": "reportlab==4.0.0",
        },
        # Общие библиотеки (Shared kernel)
        "common/": {
             "__init__.py": "",
             "db.py": """
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
""",
        }
    }

    # Функция, которая физически создает папки и файлы
    def write_structure(base, struct):
        for name, content in struct.items():
            path = os.path.join(base, name)
            
            if name.endswith("/"):
                os.makedirs(path, exist_ok=True)
                write_structure(path, content) # Рекурсия для вложенных папок
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

    # Проверка, чтобы не перезаписать случайно
    if os.path.exists(base_dir):
        print(f"⚠️ Папка '{base_dir}' уже существует.")
        print("Если хочешь пересоздать — удали её вручную.")
    else:
        os.makedirs(base_dir)
        write_structure(base_dir, structure)
        print(f"✅ Успех! Папка '{base_dir}' создана.")
        print("Внутри лежат файлы: app.py, requirements.txt и папки модулей.")

if __name__ == "__main__":
    create_dummy_project()