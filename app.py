import os
from datetime import datetime
from flask import Flask
from extensions import db
from routes.main         import main_bp
from routes.shows        import shows_bp
from routes.schedule     import schedule_bp
from routes.crew         import crew_bp
from routes.show_crew    import show_crew_bp
from routes.oss          import oss_bp
from routes.crew_import  import crew_import_bp


def create_app():
    app = Flask(__name__)

    # ── Config ────────────────────────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "adi-workflow-dev-key-change-in-prod")
    # Store the DB in the user's home dir so it works even on Google Drive mounts
    home = os.path.expanduser("~")
    default_db = f"sqlite:///{home}/.adi_workflow.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", default_db)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(main_bp)
    app.register_blueprint(shows_bp,        url_prefix="/shows")
    app.register_blueprint(schedule_bp,     url_prefix="/shows")
    app.register_blueprint(crew_bp,         url_prefix="/crew")
    app.register_blueprint(show_crew_bp,    url_prefix="/shows")
    app.register_blueprint(oss_bp,          url_prefix="/shows")
    app.register_blueprint(crew_import_bp,  url_prefix="/crew")

    # ── Context processors ────────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from models import Show
        logo_path = os.path.join(app.static_folder, "img", "logo.png")
        try:
            all_shows = Show.query.order_by(Show.name).all()
        except Exception:
            all_shows = []
        return {
            "now": datetime.utcnow(),
            "logo_exists": os.path.exists(logo_path),
            "all_shows": all_shows,
        }

    # ── Create tables + apply pending migrations + seed data ────────────────
    with app.app_context():
        db.create_all()
        # Apply any pending column-adds or data migrations defined in
        # migrations.py. Safe to run every startup — idempotent.
        try:
            from migrations import run_migrations
            run_migrations()
        except Exception as e:
            app.logger.error(f"Migration failure on startup: {e}")
        _seed_positions()
        _seed_day_templates()

    return app


def _seed_positions():
    """Load the standard position list if the table is empty."""
    from models import Position
    if Position.query.first():
        return

    defaults = [
        # title, department, type, union_eligible
        ("Executive Producer",          "Production",  "lead",      False),
        ("Technical Director",          "Production",  "lead",      False),
        ("Asst. Technical Director",    "Production",  "lead",      False),
        ("Show Caller",                 "Production",  "lead",      False),
        ("Production Manager",          "Production",  "lead",      False),
        ("Production Coordinator",      "Production",  "lead",      False),
        ("Creative Producer",           "Production",  "lead",      False),
        ("Art Director",                "Production",  "lead",      False),
        ("Asst. Stage Manager",         "Production",  "lead",      False),
        # Audio
        ("A1",                          "Audio",       "lead",      False),
        ("A2",                          "Audio",       "hand",      False),
        ("Audio System Engineer",       "Audio",       "lead",      False),
        ("SS Engineer",                 "Audio",       "specialty", False),
        ("Wireless Intercom Tech",      "Audio",       "specialty", False),
        ("Audio Head",                  "Audio",       "head",      True),
        ("Audio Hand",                  "Audio",       "hand",      True),
        # Video
        ("Video Director",              "Video",       "lead",      False),
        ("EIC",                         "Video",       "lead",      False),
        ("E2 Engineer",                 "Video",       "lead",      False),
        ("Video TD",                    "Video",       "lead",      False),
        ("Camera Director",             "Video",       "lead",      False),
        ("Camera Operator",             "Video",       "hand",      False),
        ("Jib Operator",                "Video",       "specialty", False),
        ("GFX Operator",                "Video",       "hand",      False),
        ("Pixera Operator",             "Video",       "specialty", False),
        ("Millumin Playback",           "Video",       "specialty", False),
        ("Video Head",                  "Video",       "head",      True),
        ("Video Hand",                  "Video",       "hand",      True),
        ("Camera Op (Local)",           "Video",       "hand",      True),
        # Lighting
        ("Lighting Designer",           "Lighting",    "lead",      False),
        ("Master Electrician",          "Lighting",    "lead",      False),
        ("Production Electrician",      "Lighting",    "lead",      False),
        ("Asst. Production Electrician","Lighting",    "hand",      False),
        ("LX Programmer",               "Lighting",    "specialty", False),
        ("Lighting Head",               "Lighting",    "head",      True),
        ("Lighting Hand",               "Lighting",    "hand",      True),
        # LED
        ("LED Lead",                    "LED",         "lead",      False),
        ("LED Head",                    "LED",         "head",      True),
        ("LED Hand",                    "LED",         "hand",      True),
        # Rigging
        ("Rigging PM",                  "Rigging",     "lead",      False),
        ("Lead Rigger",                 "Rigging",     "lead",      False),
        ("Lead Rigger (Laser Layout)",  "Rigging",     "specialty", False),
        ("Rigger High",                 "Rigging",     "hand",      True),
        ("Rigger Low",                  "Rigging",     "hand",      True),
        ("Asst. Electrician",           "Rigging",     "hand",      False),
        # Scenic
        ("Scenic Lead",                 "Scenic",      "lead",      False),
        ("Scenic Assistant",            "Scenic",      "hand",      False),
        ("Scenic Head",                 "Scenic",      "head",      True),
        ("Scenic Hand",                 "Scenic",      "hand",      True),
        ("Carpenter Lead",              "Scenic",      "head",      True),
        ("Carpenter",                   "Scenic",      "hand",      True),
        # General / Local Labor
        ("Steward",                     "General",     "lead",      True),
        ("Labor Coordinator",           "General",     "lead",      True),
        ("Utility / Stagehand",         "General",     "utility",   True),
        ("Utility (Truss)",             "General",     "utility",   True),
        ("Loader",                      "General",     "utility",   True),
        ("Forklift Driver",             "General",     "utility",   True),
        ("Boom Operator",               "General",     "utility",   True),
        ("Power",                       "Power",       "hand",      True),
        # Specialty
        ("AI Caption Lead",             "Specialty",   "specialty", False),
        ("Livestream Engineer",         "Specialty",   "specialty", False),
        ("Hair & Makeup",               "Specialty",   "specialty", False),
    ]

    for title, dept, typ, union in defaults:
        db.session.add(Position(title=title, department=dept, type=typ, union_eligible=union))
    db.session.commit()


def _seed_day_templates():
    """Populate DayTemplate table from defaults if empty."""
    from models import DayTemplate
    if DayTemplate.query.first():
        return

    defaults = [
        ("load_in", "Load In Day", "Load In", 1, [
            ("7:00 AM",  "CREW START"),
            ("12:30 PM", "LUNCH BREAK — 30 min"),
            ("3:00 PM",  "AFTERNOON BREAK — 15 min"),
            ("7:00 PM",  "EOD WRAP"),
        ]),
        ("show_day", "Show Day", "Show", 2, [
            ("7:00 AM",  "CREW START"),
            ("8:00 AM",  "DOORS OPEN"),
            ("9:00 AM",  "GENERAL SESSION BEGINS"),
            ("12:00 PM", "LUNCH BREAK — 60 min"),
            ("1:00 PM",  "AFTERNOON SESSION"),
            ("5:00 PM",  "END OF SHOW"),
            ("7:00 PM",  "EOD WRAP"),
        ]),
        ("tech_rehearsal", "Tech Rehearsal", None, 3, [
            ("7:00 AM",  "CREW START"),
            ("9:00 AM",  "TECH REHEARSAL BEGINS"),
            ("12:30 PM", "LUNCH BREAK — 30 min"),
            ("1:00 PM",  "TECH REHEARSAL RESUMES"),
            ("5:00 PM",  "END OF TECH"),
            ("7:00 PM",  "EOD WRAP"),
        ]),
        ("presenter_rehearsal", "Presenter Rehearsal", None, 4, [
            ("8:00 AM",  "CREW START"),
            ("9:00 AM",  "PRESENTER REHEARSAL BEGINS"),
            ("12:00 PM", "LUNCH BREAK — 30 min"),
            ("1:00 PM",  "PRESENTER REHEARSAL RESUMES"),
            ("5:00 PM",  "END OF REHEARSAL"),
            ("7:00 PM",  "EOD WRAP"),
        ]),
        ("strike", "Strike Day", "Strike", 5, [
            ("8:00 AM",  "CREW START — STRIKE BEGINS"),
            ("12:00 PM", "LUNCH BREAK — 30 min"),
            ("6:00 PM",  "STRIKE COMPLETE / EOD WRAP"),
        ]),
        ("prep", "Prep Day", "Prep", 6, [
            ("9:00 AM",  "CREW START — PREP"),
            ("12:30 PM", "LUNCH BREAK — 30 min"),
            ("6:00 PM",  "EOD WRAP"),
        ]),
    ]

    import json
    for key, label, phase_hint, sort, activities in defaults:
        t = DayTemplate(
            key=key, label=label, phase_hint=phase_hint, sort_order=sort,
            activities_json=json.dumps(activities),
        )
        db.session.add(t)
    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
