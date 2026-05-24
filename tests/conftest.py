import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def monolith_dir(tmp_path):
    """Flask монолит: 2 сервиса + 1 shared-библиотека + межмодульный импорт."""
    users = tmp_path / "users"
    users.mkdir()
    (users / "__init__.py").write_text("")
    (users / "views.py").write_text(
        "from flask import Blueprint\n"
        "from common import utils\n"          # импорт shared → даёт ребро users→common
        "user_bp = Blueprint('users', __name__)\n"
    )
    (users / "models.py").write_text(
        "from db import db\n"
        "class User(db.Model):\n"
        "    id = db.Column(db.Integer, primary_key=True)\n"
        "    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'))\n"
        "    orders = db.relationship('Order', backref='user')\n"
    )

    products = tmp_path / "products"
    products.mkdir()
    (products / "__init__.py").write_text("")
    (products / "views.py").write_text(
        "from flask import Blueprint\n"
        "from common import utils\n"          # импорт shared → даёт ребро products→common
        "from users import models as um\n"    # импорт сервиса → даёт ребро products→users
        "product_bp = Blueprint('products', __name__)\n"
    )
    (products / "requirements.txt").write_text("Pillow==10.0.0\n")

    common = tmp_path / "common"
    common.mkdir()
    (common / "__init__.py").write_text("")
    (common / "utils.py").write_text("def helper(): pass\n")

    (tmp_path / "requirements.txt").write_text("Flask==3.0.0\nrequests==2.31.0\n")

    return tmp_path


@pytest.fixture
def fastapi_monolith(tmp_path):
    """FastAPI монолит: 2 сервиса с APIRouter."""
    users = tmp_path / "users"
    users.mkdir()
    (users / "__init__.py").write_text("")
    (users / "router.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/users', tags=['users'])\n"
        "\n"
        "@router.get('/')\n"
        "def list_users(): return []\n"
    )

    orders = tmp_path / "orders"
    orders.mkdir()
    (orders / "__init__.py").write_text("")
    (orders / "router.py").write_text(
        "from fastapi import APIRouter\n"
        "from users import router as user_router\n"  # edge orders→users
        "router = APIRouter(prefix='/orders', tags=['orders'])\n"
    )

    (tmp_path / "requirements.txt").write_text("fastapi>=0.100.0\nuvicorn>=0.23.0\n")
    return tmp_path


@pytest.fixture
def django_monolith(tmp_path):
    """Django монолит: 2 приложения с urlpatterns."""
    (tmp_path / "manage.py").write_text("# django manage\n")
    (tmp_path / "requirements.txt").write_text("Django>=4.2\n")

    blog = tmp_path / "blog"
    blog.mkdir()
    (blog / "__init__.py").write_text("")
    (blog / "urls.py").write_text(
        "from django.urls import path\n"
        "from . import views\n"
        "urlpatterns = [path('', views.index)]\n"
    )
    (blog / "views.py").write_text("def index(request): pass\n")

    shop = tmp_path / "shop"
    shop.mkdir()
    (shop / "__init__.py").write_text("")
    (shop / "urls.py").write_text(
        "from django.urls import path\n"
        "urlpatterns = [path('', lambda r: None)]\n"
    )

    return tmp_path
