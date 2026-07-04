import os
import importlib
from datetime import datetime
from flask import Flask
from extensions import db


# List of (import_path, blueprint_attr, url_prefix) — driven at runtime
# so a single broken module degrades to a dead nav link, not a dead site.
# This is the general form of the July 2 requests_bp outage — hardcoding
# the sidebar href fixed the symptom, this fixes the class.
_BLUEPRINTS = [
    ("routes.main",             "main_bp",         None),
    ("routes.shows",            "shows_bp",        "/shows"),
    ("routes.schedule",         "schedule_bp",     "/shows"),
    ("routes.crew",             "crew_bp",         "/crew"),
    ("routes.show_crew",        "show_crew_bp",    "/shows"),
    ("routes.oss",              "oss_bp",          "/shows"),
    ("routes.crew_import",      "crew_import_bp",  "/crew"),
    ("routes.audit_routes",     "audit_bp",        None),
    ("routes.requests_routes",  "requests_bp",     None),
]


def create_app():
    app = Flask(__name__)

    # ── Config ────────────────────────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "adi-workflow-dev-key-change-in-prod")
    # Store the DB in the user's home dir so it works even on Google Drive mounts
    home = os.path.expanduser("~")
    default_db = f"sqlite:///{home}/.adi_workflow.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", default_db)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Max total request body size: covers request-board image uploads
    # (8 files × 5 MB per file = 40 MB) plus headroom for the crew XLSX
    # importer. Anything larger is rejected by Werkzeug before it hits a route.
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)

    # ── Blueprints (resilient loader) ────────────────────────────────────────
    # Each blueprint is imported and registered inside its own try/except.
    # A failure is captured in app.config["BLUEPRINT_ERRORS"] (a dict) so:
    #   1) the rest of the site still boots and serves 200s
    #   2) the affected feature 404s (the routes never registered)
    #   3) the failure is visible on the dashboard via a banner
    # base.html hardcodes the sidebar hrefs where possible so a missing
    # blueprint does not blow up template rendering. See July 2 hotfix.
    app.config["BLUEPRINT_ERRORS"] = {}
    for import_path, attr_name, url_prefix in _BLUEPRINTS:
        try:
            module = importlib.import_module(import_path)
            bp = getattr(module, attr_name)
            if url_prefix is None:
                app.register_blueprint(bp)
            else:
                app.register_blueprint(bp, url_prefix=url_prefix)
        except Exception as e:
            app.logger.exception("Failed to load blueprint %s.%s", import_path, attr_name)
            app.config["BLUEPRINT_ERRORS"][import_path] = str(e)

    # Install SQLAlchemy audit listeners for undo/redo. Must happen after
    # models is imported (which db.init_app already triggered).
    from audit import install_audit_listeners
    install_audit_listeners(app)

    # ── Jinja filters ─────────────────────────────────────────────────────────
    @app.template_filter("to_12hr")
    def to_12hr_filter(v):
        """
        Render a time string as 12-hour with AM/PM.
        Accepts:
          * 24hr 'HH:MM' or 'H:MM' from <input type="time"> (e.g. '06:00', '13:00')
          * 12hr strings that already have AM/PM — passed through as-is
          * anything else → returned unchanged
        """
        if v is None:
            return ""
        s = str(v).strip()
        if not s:
            return ""
        # Already 12-hour? Trust it.
        upper = s.upper()
        if "AM" in upper or "PM" in upper:
            return s
        # Split HH:MM
        parts = s.split(":")
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1][:2].isdigit():
            return s
        try:
            h = int(parts[0])
            m = int(parts[1][:2])
        except ValueError:
            return s
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return s
        ampm = "AM" if h < 12 else "PM"
        display_h = h % 12 or 12
        return f"{display_h}:{m:02d} {ampm}"

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
            "migration_error": app.config.get("MIGRATION_ERROR"),
            "blueprint_errors": app.config.get("BLUEPRINT_ERRORS") or {},
        }

    # ── Create tables + apply pending migrations + seed data ────────────────
    #
    # Migration failure is captured on app.config so the dashboard can surface
    # a red banner. Silently logging (as we did before July 4) meant a
    # half-migrated DB could keep serving traffic with only a log line to show
    # for it — that's the "silent failure on PA" pattern Larry got bitten by.
    app.config["MIGRATION_ERROR"] = None
    with app.app_context():
        db.create_all()
        try:
            from migrations import run_migrations
            run_migrations()
        except Exception as e:
            app.logger.exception("Migration failure on startup")
            app.config["MIGRATION_ERROR"] = str(e)
        _seed_positions()
        _seed_day_templates()
        _seed_requests_board()

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


def _seed_requests_board():
    """
    On first startup after the Requests board ships, populate it with the
    recent work items (marked Deployed) so Jason and Larry see history
    instead of an empty board. Idempotent: skips if the table already has
    entries, so re-runs (or manual additions) don't duplicate.
    """
    from models import Request as ReqModel
    if ReqModel.query.first():
        return

    from datetime import datetime
    now = datetime.utcnow()

    # (title, description, category, priority, requested_by, notes)
    # All will be marked status="deployed", deployed_at=now.
    seed = [
        # ── Recent — post-9/9 recovery batch ─────────────────────────────
        ("Undo/Redo audit log for all data changes",
         "SQLAlchemy event listeners capture insert/update/delete on 11 tables. "
         "Every user action is grouped by request UUID and can be undone or "
         "redone from the Recent Activity page. Answers Larry's 9/9 data-loss "
         "concern.",
         "feature", "P0", "Larry", "Layer 3 of the safety plan. Deployed 6/30."),

        ("Prompter position added to master roster",
         "Added a first-class Prompter position under Video department so it "
         "appears in the position dropdown everywhere.",
         "feature", "P2", "Larry", "Chunk 1."),

        ("Contact sheet prints blank — Chrome PDF fix",
         "Chrome's Print to PDF strips colored backgrounds by default. Added "
         "-webkit-print-color-adjust: exact + print-color-adjust: exact so the "
         "contact sheet renders correctly to PDF.",
         "bug", "P1", "Larry", "Chunk 1."),

        ("Auto-save booking and travel fields (350ms debounce)",
         "Any form with data-autosave=\"true\" now saves in the background as "
         "you edit — no more manual Save buttons on the booking + travel pages.",
         "ux", "P1", "Larry", "Chunk 2."),

        ("Travel page: sort by vendor + XLSX export + PDF export",
         "Sort dropdown, contact sheet Excel export, travel Excel export, and "
         "landscape travel PDF (WeasyPrint) with 13-column layout.",
         "feature", "P1", "Larry", "Chunk 3."),

        ("Inline + New Position modal from the roster dropdown",
         "\"+ New position…\" sentinel option in the position dropdown pops a "
         "modal to create a Position on the fly without leaving the row.",
         "feature", "P2", "Larry", "Chunk 4."),

        # ── Wishlist batch ───────────────────────────────────────────────
        ("Actual hours column next to Estimated hours on crew rows",
         "Both Est and Actual show side by side in the day editor crew table "
         "so the day-of numbers can be captured against the plan.",
         "feature", "P2", "Larry", "Wishlist item."),

        ("Duplicate Show button",
         "Deep-copies a show's Schedule Days, Activities, and Crew Rows into "
         "a new show. Wipes crew_member_id so the new show doesn't inherit "
         "specific assignments.",
         "feature", "P2", "Larry", "Wishlist item."),

        ("Crew roster: drag-to-reorder + inline edit",
         "Replaced up/down arrows with SortableJS drag handles. All roster "
         "fields (name, phone, email, position, company) are inline-editable.",
         "ux", "P2", "Larry", "Wishlist item #3."),

        ("Show crew Booking Sheet: drag-to-reorder",
         "Applied the same drag-and-drop pattern to the per-show booking sheet.",
         "ux", "P2", "Larry", "Wishlist item."),

        ("Edit CrewRow inline within an activity",
         "Row-level edits inside a schedule activity save inline instead of "
         "requiring a modal.",
         "ux", "P2", "Larry", "Wishlist item #7."),

        ("Date-change confirmation on Day Settings",
         "Changing a day's date now prompts for confirmation, since it can "
         "cascade into scheduling conflicts.",
         "ux", "P2", "Larry", "Wishlist item."),

        # ── Bigger recent features ───────────────────────────────────────
        ("Phase A: Crew Booking sheet (per-show)",
         "New per-show Booking page: track offer/booked status, contract sent, "
         "notes, and TBD open slots that can be filled in later. Includes "
         "bulk File 1 importer.",
         "feature", "P1", "Larry", "Phase A."),

        ("Phase B: Travel page (per-show)",
         "Hotel + flight fields on ShowCrewAssignment. Per-show Travel page "
         "with sortable columns and File 2 travel-column importer.",
         "feature", "P1", "Larry", "Phase B."),

        ("Phase C: F&B v2 — multi-location meal services",
         "MealService + MealServiceLocation + ShowDietaryNote models. Existing "
         "F&B SubScheduleEntries data-migrated into the new structure.",
         "feature", "P1", "Larry", "Phase C."),

        ("Crew XLSX bulk importer",
         "Upload File 1 (booking) or File 2 (travel) as .xlsx, preview matched "
         "rows, confirm to commit. Handles fuzzy name matching + position "
         "resolution.",
         "feature", "P1", "Larry", "Deployed with Phase A."),

        # ── The move we just made ────────────────────────────────────────
        ("Requests board (this page)",
         "Replaces the \"ADI Build Notes\" Google Doc with a structured, "
         "inline-editable, filterable requests board. Every change is "
         "audit-tracked so mistakes are undoable from Recent Activity.",
         "feature", "P1", "Jason",
         "Categories: Bug / Feature / UX / Question. Priorities: P0 / P1 / "
         "P2 / P3. Statuses: Requested → In Progress → Ready to Test → "
         "Deployed → Deferred. Sort_order supports drag-to-reorder within "
         "a status."),
    ]

    for i, (title, desc, cat, prio, by, notes) in enumerate(seed):
        r = ReqModel(
            title=title, description=desc,
            category=cat, priority=prio,
            status="deployed",
            requested_by=by, notes=notes,
            sort_order=i,
            deployed_at=now,
        )
        db.session.add(r)
    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
