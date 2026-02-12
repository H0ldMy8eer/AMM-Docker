
from flask import Blueprint
user_bp = Blueprint('users', __name__)

@user_bp.route('/')
def index():
    return "User List"
