import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def monolith_dir(tmp_path):
    """Минимальный тестовый монолит: 2 сервиса + 1 shared-библиотека."""
    users = tmp_path / "users"
    users.mkdir()
    (users / "__init__.py").write_text("")
    (users / "views.py").write_text(
        "from flask import Blueprint\nuser_bp = Blueprint('users', __name__)\n"
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
        "from flask import Blueprint\nproduct_bp = Blueprint('products', __name__)\n"
    )
    (products / "requirements.txt").write_text("Pillow==10.0.0\n")

    common = tmp_path / "common"
    common.mkdir()
    (common / "__init__.py").write_text("")
    (common / "utils.py").write_text("def helper(): pass\n")

    (tmp_path / "requirements.txt").write_text("Flask==3.0.0\nrequests==2.31.0\n")

    return tmp_path
