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
        "users/": {
            "__init__.py": "",
            "views.py": """
from flask import Blueprint
user_bp = Blueprint('users', __name__)

@user_bp.route('/')
def index():
    return "User List"
""",
            "models.py": "# Здесь модель User для базы данных",
        },
        # Модуль товаров (будущий микросервис 2)
        "products/": {
            "__init__.py": "",
            "views.py": """
from flask import Blueprint
product_bp = Blueprint('products', __name__)

@product_bp.route('/')
def list():
    return "Product List"
""",
            "utils.py": "import math\n# Вспомогательные функции",
        },
        # Модуль заказов (будущий микросервис 3)
        "orders/": {
            "__init__.py": "",
            "views.py": "# Логика заказов",
            # У заказов есть СВОЯ уникальная библиотека, которой нет в общем файле
            "requirements.txt": "reportlab==4.0.0", 
        },
        # Общие библиотеки (Shared kernel)
        "common/": {
             "__init__.py": "",
             "db.py": "# Общее подключение к БД",
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