from flask import Blueprint, render_template
from models import Show

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def dashboard():
    shows = Show.query.order_by(Show.show_start.desc()).all()
    return render_template("index.html", shows=shows)
