from extensions import db
from datetime import datetime
import json


# ── Lookup / reference tables ────────────────────────────────────────────────

class Client(db.Model):
    __tablename__ = "clients"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    contact     = db.Column(db.String(200))
    email       = db.Column(db.String(200))
    phone       = db.Column(db.String(50))
    address     = db.Column(db.Text)
    notes       = db.Column(db.Text)
    shows       = db.relationship("Show", back_populates="client", lazy="dynamic")

    def __repr__(self):
        return f"<Client {self.name}>"


class Venue(db.Model):
    __tablename__ = "venues"
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(200), nullable=False)
    city          = db.Column(db.String(100))
    state         = db.Column(db.String(50))
    country       = db.Column(db.String(100), default="USA")
    address       = db.Column(db.Text)
    dock_count    = db.Column(db.Integer)
    union_local   = db.Column(db.String(100))
    wifi_ssid     = db.Column(db.String(200))
    wifi_password = db.Column(db.String(200))
    notes         = db.Column(db.Text)
    shows         = db.relationship("Show", back_populates="venue", lazy="dynamic")

    def __repr__(self):
        return f"<Venue {self.name}, {self.city}>"


class Company(db.Model):
    """Production companies, vendors, union locals, etc."""
    __tablename__ = "companies"
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(200), nullable=False)
    code         = db.Column(db.String(20))        # e.g. "BAV", "CT", "VRA"
    type         = db.Column(db.String(50))        # production / vendor / union / venue
    contact_name = db.Column(db.String(200))
    email        = db.Column(db.String(200))
    phone        = db.Column(db.String(50))
    address      = db.Column(db.Text)
    notes        = db.Column(db.Text)
    crew         = db.relationship("CrewMember", back_populates="company", lazy="dynamic")

    def __repr__(self):
        return f"<Company {self.name}>"


class Position(db.Model):
    """Master list of crew positions / labor categories."""
    __tablename__ = "positions"
    id             = db.Column(db.Integer, primary_key=True)
    title          = db.Column(db.String(100), nullable=False)   # e.g. "A1", "LED Head"
    department     = db.Column(db.String(50))    # Audio / Video / Lighting / LED / Rigging / Scenic / Power / General
    type           = db.Column(db.String(30))    # lead / head / hand / utility / specialty
    union_eligible = db.Column(db.Boolean, default=False)
    rate_low       = db.Column(db.Float)
    rate_high      = db.Column(db.Float)
    notes          = db.Column(db.Text)

    def __repr__(self):
        return f"<Position {self.title}>"


class CrewMember(db.Model):
    """Global roster of people (named crew)."""
    __tablename__ = "crew_members"
    id             = db.Column(db.Integer, primary_key=True)
    first_name     = db.Column(db.String(100), nullable=False)
    last_name      = db.Column(db.String(100), nullable=False)
    company_id     = db.Column(db.Integer, db.ForeignKey("companies.id"))
    position_id    = db.Column(db.Integer, db.ForeignKey("positions.id"))
    email          = db.Column(db.String(200))
    phone          = db.Column(db.String(50))
    rate_standard  = db.Column(db.Float)
    rate_ot        = db.Column(db.Float)
    rate_dt        = db.Column(db.Float)
    meal_penalty   = db.Column(db.Float)
    per_diem       = db.Column(db.Float)
    active         = db.Column(db.Boolean, default=True)
    notes          = db.Column(db.Text)
    # Phase D wishlist: manual roster ordering — up/down arrows move a
    # person around. NULL means "not manually ordered yet" and falls back
    # to alphabetical by last_name in the view.
    sort_order     = db.Column(db.Integer)
    company        = db.relationship("Company", back_populates="crew")
    position       = db.relationship("Position")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __repr__(self):
        return f"<CrewMember {self.full_name}>"


# ── Show ─────────────────────────────────────────────────────────────────────

SHOW_STATUS = ["Planning", "Active", "Closed", "Cancelled"]

class Show(db.Model):
    __tablename__ = "shows"
    id            = db.Column(db.Integer, primary_key=True)
    code          = db.Column(db.String(50))          # e.g. "GHC26"
    name          = db.Column(db.String(200), nullable=False)
    client_id     = db.Column(db.Integer, db.ForeignKey("clients.id"))
    venue_id      = db.Column(db.Integer, db.ForeignKey("venues.id"))
    room_name     = db.Column(db.String(200))
    load_in_date  = db.Column(db.Date)
    show_start    = db.Column(db.Date)
    show_end      = db.Column(db.Date)
    strike_date   = db.Column(db.Date)
    version       = db.Column(db.Integer, default=1)
    status        = db.Column(db.String(30), default="Planning")
    notes         = db.Column(db.Text)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client        = db.relationship("Client", back_populates="shows")
    venue         = db.relationship("Venue", back_populates="shows")
    days          = db.relationship("ScheduleDay", back_populates="show",
                                    order_by="ScheduleDay.date", cascade="all, delete-orphan")
    phases        = db.relationship("ProductionPhase", back_populates="show",
                                    order_by="ProductionPhase.start_date",
                                    cascade="all, delete-orphan")
    crew_assignments = db.relationship("ShowCrewAssignment", back_populates="show",
                                       cascade="all, delete-orphan")

    @property
    def version_label(self):
        return f"Version {self.version}"

    @property
    def date_range(self):
        """Derives from phases if available, otherwise falls back to raw date columns."""
        if self.phases:
            dates = [p.start_date for p in self.phases if p.start_date] + \
                    [p.end_date   for p in self.phases if p.end_date]
            if dates:
                return f"{min(dates).strftime('%b %-d')} – {max(dates).strftime('%b %-d, %Y')}"
        if self.load_in_date and self.strike_date:
            return f"{self.load_in_date.strftime('%b %-d')} – {self.strike_date.strftime('%b %-d, %Y')}"
        return "Dates TBD"

    def _phase_date(self, phase_type, attr):
        """Helper to pull a date from a specific phase type."""
        for p in (self.phases or []):
            if p.phase_type == phase_type and getattr(p, attr):
                return getattr(p, attr)
        return None

    def __repr__(self):
        return f"<Show {self.name}>"


# ── Schedule ─────────────────────────────────────────────────────────────────

PHASES = [
    "Equipment Delivery",
    "Load In",
    "Setup",
    "Tech Rehearsal",
    "Executive Rehearsal",
    "Presenter Rehearsal",
    "Show Day",
    "Strike",
    "Travel",
    "Dark",
]


class ScheduleDay(db.Model):
    __tablename__ = "schedule_days"
    id          = db.Column(db.Integer, primary_key=True)
    show_id     = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    date        = db.Column(db.Date, nullable=False)
    label       = db.Column(db.String(200))         # e.g. "Load In Day 1"
    call_time   = db.Column(db.String(20))           # e.g. "6:00 AM"
    wrap_time   = db.Column(db.String(20))           # e.g. "10:00 PM"
    phase       = db.Column(db.String(50))
    milestones  = db.Column(db.Text)                 # newline-separated milestone notes
    notes       = db.Column(db.Text)

    # Travel day fields — only used when phase == "Travel"
    travel_flight_number   = db.Column(db.String(20))
    travel_airline         = db.Column(db.String(100))
    travel_depart_airport  = db.Column(db.String(10))   # IATA code, e.g. "DFW"
    travel_arrive_airport  = db.Column(db.String(10))
    travel_depart_time     = db.Column(db.String(20))
    travel_arrive_time     = db.Column(db.String(20))
    travel_hotel_name      = db.Column(db.String(200))
    travel_hotel_confirm   = db.Column(db.String(100))

    # Wristbands (OSS Wristbands tab). The "crew on day" count is derived
    # from the activity crew rows, but the override (if set) replaces it.
    wristband_crew_override = db.Column(db.Integer)     # NULL → use auto-derived
    wristband_extras        = db.Column(db.Integer)     # additional bands (VIPs, talent, etc.)
    wristband_notes         = db.Column(db.Text)

    show        = db.relationship("Show", back_populates="days")
    activities  = db.relationship("ScheduleActivity", back_populates="day",
                                  order_by="ScheduleActivity.sort_order",
                                  cascade="all, delete-orphan")
    oss_entries = db.relationship("SubScheduleEntry", back_populates="schedule_day",
                                  order_by="SubScheduleEntry.sort_order",
                                  cascade="all, delete-orphan")

    @property
    def day_header(self):
        if self.date:
            return self.date.strftime("%A, %B %-d, %Y")
        return "Date TBD"

    @property
    def time_window(self):
        if self.call_time and self.wrap_time:
            return f"{self.call_time} – {self.wrap_time}"
        return ""

    @property
    def milestone_list(self):
        if self.milestones:
            return [m.strip() for m in self.milestones.splitlines() if m.strip()]
        return []

    # ── Wristband helpers ────────────────────────────────────────────────
    @property
    def computed_crew_count(self):
        """
        Auto-derived headcount for this day: unique named crew + sum of
        unnamed qty across all activities. Counts each named person once
        even if they appear in multiple activities; unnamed rows are summed
        as 'qty' since each represents a distinct slot.
        """
        named_ids = set()
        unnamed_total = 0
        for act in self.activities:
            for row in act.crew_rows:
                if row.is_group_header:
                    continue
                if row.crew_member_id:
                    named_ids.add(row.crew_member_id)
                else:
                    unnamed_total += (row.qty or 1)
        return len(named_ids) + unnamed_total

    @property
    def effective_crew_count(self):
        """Override (when set) beats auto-derived count."""
        if self.wristband_crew_override is not None:
            return self.wristband_crew_override
        return self.computed_crew_count

    @property
    def total_wristbands(self):
        return self.effective_crew_count + (self.wristband_extras or 0)

    def __repr__(self):
        return f"<ScheduleDay {self.date}>"


class ScheduleActivity(db.Model):
    """A time-stamped block within a day (e.g. '8:00 AM — LOAD IN / SETUP RIGGING')."""
    __tablename__ = "schedule_activities"
    id          = db.Column(db.Integer, primary_key=True)
    day_id      = db.Column(db.Integer, db.ForeignKey("schedule_days.id"), nullable=False)
    time        = db.Column(db.String(20))           # e.g. "8:00 AM"
    description = db.Column(db.String(500), nullable=False)
    notes       = db.Column(db.Text)
    sort_order  = db.Column(db.Integer, default=0)

    day         = db.relationship("ScheduleDay", back_populates="activities")
    crew_rows   = db.relationship("CrewRow", back_populates="activity",
                                  order_by="CrewRow.sort_order",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Activity {self.time} {self.description[:40]}>"


CREW_TYPES = ["Lead Crew", "Local Crew", "Vendor Crew", "Union Crew"]


class CrewRow(db.Model):
    """
    A single crew line inside an activity block.
    e.g.  Qty=1  Hrs=11  Position='A1'  Name='Ollie M.'  Type='Lead Crew'
    Can also represent a section header (group_header=True) like 'LEAD CREW'.
    """
    __tablename__ = "crew_rows"
    id              = db.Column(db.Integer, primary_key=True)
    activity_id     = db.Column(db.Integer, db.ForeignKey("schedule_activities.id"), nullable=False)
    sort_order      = db.Column(db.Integer, default=0)

    # If True this row is a section header label, not a crew line
    is_group_header = db.Column(db.Boolean, default=False)
    group_label     = db.Column(db.String(100))      # e.g. "LEAD CREW"

    # Crew line fields
    qty             = db.Column(db.Integer, default=1)
    hours           = db.Column(db.Float)      # ESTIMATED / planned hours
    actual_hours    = db.Column(db.Float)      # ACTUAL hours worked (post-show)
    position        = db.Column(db.String(100))      # free-text or from Position table
    position_id     = db.Column(db.Integer, db.ForeignKey("positions.id"), nullable=True)
    crew_member_id  = db.Column(db.Integer, db.ForeignKey("crew_members.id"), nullable=True)
    name_override   = db.Column(db.String(200))      # if not linked to crew_member
    crew_type       = db.Column(db.String(50), default="Lead Crew")
    notes           = db.Column(db.Text)

    activity        = db.relationship("ScheduleActivity", back_populates="crew_rows")
    crew_member     = db.relationship("CrewMember")
    position_ref    = db.relationship("Position")

    @property
    def display_name(self):
        if self.crew_member:
            return self.crew_member.full_name
        return self.name_override or "TBD"

    def __repr__(self):
        return f"<CrewRow {self.qty}x {self.position}>"


# ── Production Phases (date ranges per show) ─────────────────────────────────

PHASE_TYPES = ["Prep", "Load In", "Show", "Strike", "Custom"]

PHASE_COLORS = {
    "Prep":    "#7C3AED",
    "Load In": "#1D4ED8",
    "Show":    "#B45309",
    "Strike":  "#9F1239",
    "Custom":  "#0F766E",
}


class ProductionPhase(db.Model):
    """A named date range within a show (Prep, Load In, Show, Strike, Custom)."""
    __tablename__ = "production_phases"
    id         = db.Column(db.Integer, primary_key=True)
    show_id    = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    name       = db.Column(db.String(200), nullable=False)   # e.g. "Lighting Prep"
    phase_type = db.Column(db.String(50), default="Custom")  # Prep/Load In/Show/Strike/Custom
    start_date = db.Column(db.Date)
    end_date   = db.Column(db.Date)
    notes      = db.Column(db.Text)

    show = db.relationship("Show", back_populates="phases")

    @property
    def color(self):
        return PHASE_COLORS.get(self.phase_type, "#0F766E")

    @property
    def date_range_display(self):
        if self.start_date and self.end_date:
            if self.start_date == self.end_date:
                return self.start_date.strftime("%b %-d, %Y")
            return f"{self.start_date.strftime('%b %-d')} – {self.end_date.strftime('%b %-d, %Y')}"
        if self.start_date:
            return self.start_date.strftime("%b %-d, %Y")
        return "Dates TBD"

    def __repr__(self):
        return f"<ProductionPhase {self.name}>"


# ── Day Templates ────────────────────────────────────────────────────────────

class DayTemplate(db.Model):
    """
    Reusable activity skeletons applied to schedule days.
    phase_hint links this template to a production phase type for auto-generate.
    activities_json: JSON list of [time, description] pairs.
    """
    __tablename__ = "day_templates"
    id              = db.Column(db.Integer, primary_key=True)
    key             = db.Column(db.String(50), unique=True, nullable=False)
    label           = db.Column(db.String(100), nullable=False)
    phase_hint      = db.Column(db.String(50))   # "Prep"|"Load In"|"Show"|"Strike"|"Custom"|None
    activities_json = db.Column(db.Text, default="[]")
    sort_order      = db.Column(db.Integer, default=0)

    @property
    def activities(self):
        try:
            return json.loads(self.activities_json or "[]")
        except Exception:
            return []

    @activities.setter
    def activities(self, val):
        self.activities_json = json.dumps(val)

    def to_dict(self):
        return {"label": self.label, "activities": self.activities}

    def __repr__(self):
        return f"<DayTemplate {self.key}>"


# ── Meal-break detection (used by the F&B unification UI) ────────────────────
#
# An activity is treated as a meal break if its description contains any of
# these keywords. "Meal" catches things like "BOXED MEAL"; "Lunch", "Dinner",
# "Breakfast" cover the obvious cases. We deliberately exclude bare "break"
# because morning/afternoon coffee breaks aren't meals.
MEAL_KEYWORDS = ("LUNCH", "DINNER", "BREAKFAST", "MEAL")


def is_meal_break(activity):
    """Return True if a ScheduleActivity looks like a meal break."""
    if not activity or not activity.description:
        return False
    desc = activity.description.upper()
    return any(kw in desc for kw in MEAL_KEYWORDS)


# ── Sub-schedules / OSS (On-Site Schedule) ───────────────────────────────────
#
# Each row in sub_schedule_entries belongs to one show, attaches to one
# ScheduleDay, and is tagged with a department type from SUB_SCHEDULE_TYPES.
# The OSS page in the UI uses one tab per type plus a Master Schedule tab
# that merges entries across types chronologically.

SUB_SCHEDULE_TYPES = [
    "Dock",
    "Hazer",
    "Doors",
    "Security",
    "F&B",
    "House LX",
    "HVAC",
    "Wristbands",
    "COMS",
    "Cleaning",
]

# UI metadata for OSS tabs. `label` is what the user sees, `icon` decorates
# the tab, `sort` controls tab order. The model stores the raw `type` key.
SUB_SCHEDULE_META = {
    "Dock":       {"label": "Dock",         "icon": "🚚", "sort": 1},
    "Hazer":      {"label": "Haze",         "icon": "💨", "sort": 2},
    "Doors":      {"label": "Doors",        "icon": "🔒", "sort": 3},
    "Security":   {"label": "Security",     "icon": "🛡",  "sort": 4},
    "F&B":        {"label": "F&B",          "icon": "🍽", "sort": 5},
    "House LX":   {"label": "House Lights", "icon": "💡", "sort": 6},
    "HVAC":       {"label": "HVAC / AC",    "icon": "❄",  "sort": 7},
    "Wristbands": {"label": "Wristbands",   "icon": "🎫", "sort": 8},
    "COMS":       {"label": "COMS",         "icon": "🎧", "sort": 9},
    "Cleaning":   {"label": "Cleaning",     "icon": "🧹", "sort": 10},
}


class ShowCrewAssignment(db.Model):
    """
    Links a crew member to a specific show, with booking info.
    Only assigned crew appear in the day-editor dropdown for that show.

    Booking fields (added Phase A): track a person's role-on-this-show
    and personal date window. `booking_task` is a free-text label like
    "PREP", "3 Show", "Set Up", "Strike" — matches how ADI's existing
    crew sheets are organized.
    """
    __tablename__ = "show_crew_assignments"
    id             = db.Column(db.Integer, primary_key=True)
    show_id        = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    crew_member_id = db.Column(db.Integer, db.ForeignKey("crew_members.id"), nullable=False)
    role_override  = db.Column(db.String(100))  # optional show-specific role note
    booking_task   = db.Column(db.String(50))   # PREP / 3 Show / Set Up / Strike / etc.
    travel_in_date = db.Column(db.Date)
    start_date     = db.Column(db.Date)         # first on-site day
    end_date       = db.Column(db.Date)         # last on-site day
    travel_out_date= db.Column(db.Date)
    # Manual reorder within a booking task card on the Show Crew page.
    sort_order     = db.Column(db.Integer)
    # ── Phase B: per-crew-per-show travel detail ──────────────────────────
    hotel_name         = db.Column(db.String(200))
    hotel_check_in     = db.Column(db.Date)
    hotel_check_out    = db.Column(db.Date)
    hotel_confirmation = db.Column(db.String(100))
    hotel_cost         = db.Column(db.Float)
    arrival_flight     = db.Column(db.String(50))   # e.g. "SW WN2877"
    arrival_time       = db.Column(db.String(20))   # e.g. "5:35pm"
    departure_flight   = db.Column(db.String(50))
    departure_time     = db.Column(db.String(20))
    itinerary_link     = db.Column(db.String(500))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("show_id", "crew_member_id",
                                          name="uq_show_crew"),)

    show        = db.relationship("Show", back_populates="crew_assignments")
    crew_member = db.relationship("CrewMember")

    @property
    def hotel_nights(self):
        """Derived from check_in/out — saves storing a redundant column."""
        if self.hotel_check_in and self.hotel_check_out:
            delta = (self.hotel_check_out - self.hotel_check_in).days
            return max(delta, 0)
        return None

    def __repr__(self):
        return f"<ShowCrewAssignment show={self.show_id} crew={self.crew_member_id}>"


class ShowOpenSlot(db.Model):
    """
    An unfilled crew position on a show — what ADI's sheets call
    'LOCAL LABOR' or 'TBD' rows. Has the same booking-info shape as
    a ShowCrewAssignment but no person attached. When filled, you
    convert it into a ShowCrewAssignment (and delete the slot).
    """
    __tablename__ = "show_open_slots"
    id               = db.Column(db.Integer, primary_key=True)
    show_id          = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    position_id      = db.Column(db.Integer, db.ForeignKey("positions.id"))  # nullable for "position TBD"
    placeholder_label= db.Column(db.String(200))   # e.g. "LED Lead — Set Up" if no Position picked
    booking_task     = db.Column(db.String(50))
    travel_in_date   = db.Column(db.Date)
    start_date       = db.Column(db.Date)
    end_date         = db.Column(db.Date)
    travel_out_date  = db.Column(db.Date)
    notes            = db.Column(db.Text)
    # Manual reorder within a booking task card on the Show Crew page.
    sort_order       = db.Column(db.Integer)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    show     = db.relationship("Show")
    position = db.relationship("Position")

    @property
    def display_title(self):
        if self.position:
            base = self.position.title
        else:
            base = self.placeholder_label or "TBD"
        if self.placeholder_label and self.position:
            return f"{base} — {self.placeholder_label}"
        return base

    def __repr__(self):
        return f"<ShowOpenSlot show={self.show_id} {self.display_title!r}>"


class SubScheduleEntry(db.Model):
    """
    Generic row for any OSS sub-schedule type (Dock, F&B, Wristbands, etc.).

    Each entry is anchored to one ScheduleDay so it always falls on a day
    that exists in the show's production schedule. The `date` property is
    derived from the linked ScheduleDay.
    """
    __tablename__ = "sub_schedule_entries"
    id              = db.Column(db.Integer, primary_key=True)
    show_id         = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    schedule_day_id = db.Column(db.Integer, db.ForeignKey("schedule_days.id"), nullable=False)
    # Optional link to a specific activity within the day. When set, this
    # entry's effective_time pulls from the linked activity (so it follows
    # any time changes there). When NULL, the entry uses its own `time`.
    activity_id     = db.Column(db.Integer, db.ForeignKey("schedule_activities.id"), nullable=True)
    type            = db.Column(db.String(50), nullable=False)   # one of SUB_SCHEDULE_TYPES
    time            = db.Column(db.String(20))                   # "HH:MM" 24hr — used when activity_id is NULL
    activity        = db.Column(db.String(500))                  # freeform label (e.g. "Crew lunch")
    duration_hrs    = db.Column(db.Float)
    count           = db.Column(db.Integer)                      # wristband qty, F&B headcount, COMS units, etc.
    notes           = db.Column(db.Text)
    sort_order      = db.Column(db.Integer, default=0)

    show           = db.relationship("Show")
    schedule_day   = db.relationship("ScheduleDay", back_populates="oss_entries")
    linked_activity = db.relationship("ScheduleActivity")

    @property
    def date(self):
        """Convenience accessor — actual date lives on the linked ScheduleDay."""
        return self.schedule_day.date if self.schedule_day else None

    @property
    def effective_time(self):
        """
        The time this entry actually happens at:
          * If linked to an activity → the activity's time (auto-follows).
          * Otherwise → the entry's own free-form `time`.
        """
        if self.linked_activity and self.linked_activity.time:
            return self.linked_activity.time
        return self.time

    @property
    def is_linked(self):
        """True when this entry follows an activity's time."""
        return self.activity_id is not None

    @property
    def meta(self):
        """UI metadata (label, icon) for this entry's type."""
        return SUB_SCHEDULE_META.get(self.type, {"label": self.type, "icon": "•", "sort": 99})

    def __repr__(self):
        return f"<SubSchedule {self.type} day={self.schedule_day_id} act={self.activity_id} {self.time}>"



# ── COMS (intercom + radio assignments per show) ─────────────────────────────
#
# Two tables:
#   * ShowCommChannel       — per-show channel names ("Main", "LX", "Cam", ...)
#   * CrewCommAssignment    — per-crew-member gear spec on this show
#
# The OSS COMS tab renders both together: the channel list is editable at the
# top, the crew table beneath is one row per ShowCrewAssignment and stores
# radio/headset/pack details + selected channels.

COM_PACK_TYPES  = ["Wired", "Wireless"]
COM_PACK_BRANDS = ["Riedel", "ClearCom", "Telex", "HME", "Other"]

# Typical number of channel keys per beltpack, by brand. Used for a SOFT
# warning when the user assigns more channels than the brand's common
# model supports. The hard cap (set in the route + UI) is 6 for all.
#   Riedel Bolero: 6-key
#   ClearCom HelixNet: 4-channel beltpack (Encore similar)
#   Telex RTS BP-2002 / BP-4002: 2 or 4 channel
#   HME DX series / production intercom: typically 2-4 channels
COM_PACK_BRAND_LIMITS = {
    "Riedel":   6,
    "ClearCom": 4,
    "Telex":    2,
    "HME":      4,
    "Other":    6,
}

# Hard cap applied to every beltpack regardless of brand.
COM_PACK_HARD_CAP = 6

# Number of radio channel slots every show gets. Two-way radios commonly
# support 16 programmable channels.
RADIO_CHANNEL_SLOTS = 16


class RadioChannel(db.Model):
    """A single radio channel slot for a show. Every show gets 16."""
    __tablename__ = "radio_channels"
    id      = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    slot    = db.Column(db.Integer, nullable=False)   # 1..RADIO_CHANNEL_SLOTS
    name    = db.Column(db.String(50))

    __table_args__ = (db.UniqueConstraint("show_id", "slot",
                                          name="uq_radio_channel_slot"),)

    show    = db.relationship("Show")

    def __repr__(self):
        return f"<RadioChannel show={self.show_id} slot={self.slot} '{self.name or ''}'>"


class ShowCommChannel(db.Model):
    """A single COMS channel defined for a show (e.g. 'Main', 'LX', 'Cam')."""
    __tablename__ = "show_comm_channels"
    id         = db.Column(db.Integer, primary_key=True)
    show_id    = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    name       = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    show       = db.relationship("Show")

    def __repr__(self):
        return f"<ShowCommChannel show={self.show_id} '{self.name}'>"


class CrewCommAssignment(db.Model):
    """
    A crew member's COMS gear assignment for a specific show.
    Auto-created on first view of the COMS tab for any crew that's assigned
    to the show but doesn't have an assignment row yet.
    """
    __tablename__ = "crew_comm_assignments"
    id              = db.Column(db.Integer, primary_key=True)
    show_id         = db.Column(db.Integer, db.ForeignKey("shows.id"),       nullable=False)
    crew_member_id  = db.Column(db.Integer, db.ForeignKey("crew_members.id"), nullable=False)
    radio           = db.Column(db.Boolean, default=False)   # two-way radio
    headset         = db.Column(db.Boolean, default=False)   # intercom pack (Bolero / HelixNet / etc.)
    pack_type       = db.Column(db.String(20))               # Wired / Wireless
    pack_brand      = db.Column(db.String(50))               # Riedel / ClearCom / Telex / HME / Other
    pack_brand_other = db.Column(db.String(100))             # used when pack_brand == "Other"
    channel_ids     = db.Column(db.Text)                     # CSV of ShowCommChannel ids
    notes           = db.Column(db.Text)

    __table_args__  = (db.UniqueConstraint("show_id", "crew_member_id",
                                           name="uq_show_crewcomm"),)

    show            = db.relationship("Show")
    crew_member     = db.relationship("CrewMember")

    @property
    def channel_id_list(self):
        """
        List of channel ids in slot order. Position N (0-indexed) in the
        list is what's assigned to key N+1 on the physical beltpack.
        `None` entries represent intentionally empty slots
        (e.g. K1=Main, K2=None, K3=LX is a real production layout).
        Trailing empty slots are trimmed.
        """
        if not self.channel_ids:
            return []
        out = []
        for piece in self.channel_ids.split(","):
            piece = piece.strip()
            if piece.isdigit():
                out.append(int(piece))
            else:
                out.append(None)
        while out and out[-1] is None:
            out.pop()
        return out

    @channel_id_list.setter
    def channel_id_list(self, ids):
        parts = []
        for i in ids:
            parts.append(str(i) if i else "")
        while parts and not parts[-1]:
            parts.pop()
        self.channel_ids = ",".join(parts) if parts else None

    @property
    def filled_channel_count(self):
        """Number of slots that actually have a channel assigned (skips gaps)."""
        return sum(1 for i in self.channel_id_list if i)

    def __repr__(self):
        return f"<CrewCommAssignment show={self.show_id} crew={self.crew_member_id}>"



# ── Crew bulk import (upload → preview → commit) ─────────────────────────────
#
# Holds a parsed XLSX upload between the upload and commit steps. Each session
# stores the rows the parser found PLUS the match decisions the user makes in
# the preview UI (add / update / skip + which existing crew to merge into +
# whether to create new positions / companies). Cleaned up on commit/cancel.

IMPORT_STATUS = ["pending", "applied", "cancelled"]


class CrewImportSession(db.Model):
    __tablename__ = "crew_import_sessions"
    id             = db.Column(db.Integer, primary_key=True)
    uploaded_at    = db.Column(db.DateTime, default=datetime.utcnow)
    filename       = db.Column(db.String(255))
    # Phase A: when set, the importer also creates/updates the
    # ShowCrewAssignment rows on this show using the parsed booking info
    # (Booking Task / Travel In / Start / End / Travel Out). When NULL,
    # the importer only touches the master crew roster.
    target_show_id = db.Column(db.Integer, db.ForeignKey("shows.id"))
    target_show    = db.relationship("Show")
    # rows_json: JSON list of dicts, each row from the parser plus a
    # "decision" key the preview UI writes into on commit. Shape:
    #   {
    #     "n": 1,                              # 1-based row number for display
    #     "first_name": "...", "last_name": "...",
    #     "email": "...", "phone": "...",
    #     "position": "raw string from file", "company": "raw string from file",
    #     "matched_id": <crew_member.id or None>,
    #     "match_reason": "email" | "name+company" | None,
    #     "fillable_fields": ["email", "phone", ...],   # blanks we'd fill
    #     "conflicts": {"email": ("existing", "from file"), ...},
    #     "position_action": "exact" | "new" | "missing",  # decided per row
    #     "company_action":  "exact" | "new" | "missing",
    #     "decision": "add" | "update" | "skip"          # set on commit
    #   }
    rows_json   = db.Column(db.Text)
    status      = db.Column(db.String(20), default="pending")
    summary     = db.Column(db.Text)   # short JSON status set after commit

    @property
    def rows(self):
        return json.loads(self.rows_json or "[]")

    @rows.setter
    def rows(self, value):
        self.rows_json = json.dumps(value)

    def __repr__(self):
        return f"<CrewImportSession {self.id} {self.filename} {self.status}>"



# ── Phase C: F&B v2 — meal services with multi-location support ──────────────
#
# Replaces the generic F&B SubScheduleEntry with a structured planner:
#   * MealService     — one "meal event" (Breakfast, Lunch, Dinner, All Day
#                       Beverages, ...) on a specific show day, optionally
#                       linked to a schedule activity for meal-break sync.
#   * MealServiceLocation — 1..N locations per service (Backstage, FOH,
#                       Local Labor, Talent Green Room, ...). Total headcount
#                       is the sum across locations.
#   * ShowDietaryNote — per-show dietary preference rollup (e.g. "30%
#                       vegetarian", "2 GF, 1 vegan").

MEAL_KINDS = ["breakfast", "lunch", "dinner", "beverages", "snack", "other"]


class MealService(db.Model):
    __tablename__ = "meal_services"
    id              = db.Column(db.Integer, primary_key=True)
    show_id         = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    schedule_day_id = db.Column(db.Integer, db.ForeignKey("schedule_days.id"), nullable=False)
    # Optional link to a specific schedule activity (e.g. the LUNCH BREAK
    # activity). Used by the meal-break detector.
    activity_id     = db.Column(db.Integer, db.ForeignKey("schedule_activities.id"), nullable=True)
    name            = db.Column(db.String(200), nullable=False)   # "Breakfast", "All Day Beverages", ...
    kind            = db.Column(db.String(30), default="other")   # one of MEAL_KINDS
    is_recurring    = db.Column(db.Boolean, default=False)        # True for All Day Beverages type
    notes           = db.Column(db.Text)
    sort_order      = db.Column(db.Integer, default=0)

    show            = db.relationship("Show")
    schedule_day    = db.relationship("ScheduleDay")
    linked_activity = db.relationship("ScheduleActivity")
    locations       = db.relationship("MealServiceLocation",
                                      back_populates="meal_service",
                                      order_by="MealServiceLocation.sort_order, MealServiceLocation.id",
                                      cascade="all, delete-orphan")

    @property
    def total_headcount(self):
        return sum((loc.headcount or 0) for loc in self.locations)

    @property
    def earliest_time(self):
        """Earliest start_time across locations (for sorting/display)."""
        times = [loc.start_time for loc in self.locations if loc.start_time]
        return min(times) if times else None

    @property
    def is_linked(self):
        return self.activity_id is not None

    def __repr__(self):
        return f"<MealService {self.name} day={self.schedule_day_id}>"


class MealServiceLocation(db.Model):
    __tablename__ = "meal_service_locations"
    id              = db.Column(db.Integer, primary_key=True)
    meal_service_id = db.Column(db.Integer, db.ForeignKey("meal_services.id"), nullable=False)
    location_name   = db.Column(db.String(200))   # "Backstage", "FOH MainStage", ...
    start_time      = db.Column(db.String(20))    # "HH:MM"
    end_time        = db.Column(db.String(20))
    headcount       = db.Column(db.Integer)
    notes           = db.Column(db.Text)
    sort_order      = db.Column(db.Integer, default=0)

    meal_service    = db.relationship("MealService", back_populates="locations")

    def __repr__(self):
        return f"<MealServiceLocation {self.location_name} service={self.meal_service_id}>"


class ShowDietaryNote(db.Model):
    """Per-show rollup of dietary preferences (Vegetarian %, GF count, etc.)."""
    __tablename__ = "show_dietary_notes"
    id         = db.Column(db.Integer, primary_key=True)
    show_id    = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    preference = db.Column(db.String(100), nullable=False)   # "Vegetarian", "GF", ...
    percentage = db.Column(db.Integer)   # 0-100, optional
    count      = db.Column(db.Integer)   # optional headcount, e.g. "3 GF"
    notes      = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)

    show       = db.relationship("Show")

    def __repr__(self):
        return f"<ShowDietaryNote {self.preference} show={self.show_id}>"
