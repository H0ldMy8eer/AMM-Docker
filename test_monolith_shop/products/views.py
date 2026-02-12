
from flask import Blueprint
product_bp = Blueprint('products', __name__)

@product_bp.route('/')
def list():
    return "Product List"
