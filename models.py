from extensions import db
from sqlalchemy.orm import validates
from datetime import datetime
import json

import brand
import time_utils


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

    # Names arrive from four different write paths (add, edit, bulk edit, the
    # XLSX importer). Normalising on the model catches all of them, including
    # any added later. A stray trailing space is not cosmetic: it produced a
    # crew member rendering as "First  Last" with a double gap, and made two
    # otherwise-identical placeholder records look like distinct people.
    @validates("first_name", "last_name")
    def _tidy_name(self, key, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    #: Names that almost certainly mean "we haven't been told who yet".
    PLACEHOLDER_NAMES = {"first", "last", "first last", "firstname",
                         "lastname", "test", "tbd", "tba", "xxx", "name",
                         "first name", "last name", "unknown", "n/a"}

    @property
    def looks_like_placeholder(self):
        """True when this record reads as a stand-in rather than a person.

        These inflate crew headcounts on schedules and exports, so they are
        worth flagging at the point someone saves one.
        """
        first = (self.first_name or "").strip().lower()
        last = (self.last_name or "").strip().lower()
        return (first in self.PLACEHOLDER_NAMES
                or last in self.PLACEHOLDER_NAMES
                or f"{first} {last}".strip() in self.PLACEHOLDER_NAMES)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_unnamed_slot(self):
        """Stricter than ``looks_like_placeholder`` — and deliberately so.

        ``looks_like_placeholder`` drives a save-time warning, where a false
        positive costs the user a shrug. This drives NAME SUBSTITUTION, where a
        false positive hides a real person from a call sheet. So it fires only
        when the whole name is a stand-in, not when one half happens to match:
        a real crew member surnamed "Name" or "Last" keeps their name.
        """
        first = (self.first_name or "").strip().lower()
        last = (self.last_name or "").strip().lower()
        both = f"{first} {last}".strip()
        if both in self.PLACEHOLDER_NAMES:
            return True
        first_ph = (not first) or first in self.PLACEHOLDER_NAMES
        last_ph = (not last) or last in self.PLACEHOLDER_NAMES
        return first_ph and last_ph and bool(both)

    @property
    def display_label(self):
        """What to render on schedules, call sheets and exports.

        An unnamed slot is not a mistake — it is a called position nobody is
        booked into yet, and "SPARKS Lead Rigger" tells a reader far more than
        "First Last". Falls back through company-only and position-only to a
        bare "TBD" so a thin record never renders as a fake person.
        """
        if not self.is_unnamed_slot:
            return self.full_name
        company = ""
        if self.company:
            company = (self.company.code or self.company.name or "").strip()
        position = (self.position.title or "").strip() if self.position else ""
        if company and position:
            return f"{company} {position}"
        if company:
            return f"{company} — TBD"
        if position:
            return f"{position} — TBD"
        return "TBD"

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
    # #31 — designated travel window; crew Travel In/Out auto-fill from these
    # when assigned to the show. Set via markers on the Schedule Overview.
    travel_window_start = db.Column(db.Date)
    travel_window_end   = db.Column(db.Date)
    # Rollout control for the breaks/meals overhaul (2026-08-11). Off means
    # this show behaves exactly as before — the new code is not even read.
    # Lets the overhaul go live one show at a time, and be backed out of a
    # show instantly without touching data.
    uses_new_breaks     = db.Column(db.Boolean, default=False)
    # #48 — show key-art; used as a header image on all generated paperwork.
    artwork_filename    = db.Column(db.String(300))
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

    # ── Everything else a show owns ─────────────────────────────────────────
    #
    # Added 2026-08-12. Deleting show 5 left **216 rows behind** in the four
    # tables that had no collection here: crew_comm_assignments 88,
    # meal_services 56 (and 56 locations under them), crew_breaks 40,
    # radio_channels 32. `days`, `phases` and `crew_assignments` cascaded and
    # left nothing — the leak was exactly the set of tables missing from this
    # list, which is why the rest are added now rather than only the four that
    # happened to hold data.
    #
    # An orphan is invisible in the app, so nothing complains: it is found
    # only by asking the database directly. It is not harmless either — a
    # crew break holding a `meal_service_id` is a ghost feeding a service, and
    # `crew_breaks.activity_id` is UNIQUE, so a stale row can collide with a
    # future insert (see ScheduleActivity.crew_break).
    meal_services    = db.relationship("MealService", back_populates="show",
                                       cascade="all, delete-orphan")
    crew_breaks      = db.relationship("CrewBreak", back_populates="show",
                                       cascade="all, delete-orphan")
    radio_channels   = db.relationship("RadioChannel", back_populates="show",
                                       cascade="all, delete-orphan")
    comm_assignments = db.relationship("CrewCommAssignment", back_populates="show",
                                       cascade="all, delete-orphan")
    comm_channels    = db.relationship("ShowCommChannel", back_populates="show",
                                       cascade="all, delete-orphan")
    dietary_notes    = db.relationship("ShowDietaryNote", back_populates="show",
                                       cascade="all, delete-orphan")
    open_slots       = db.relationship("ShowOpenSlot", back_populates="show",
                                       cascade="all, delete-orphan")
    oss_entries      = db.relationship("SubScheduleEntry", back_populates="show",
                                       cascade="all, delete-orphan")
    # No `show` relationship on these two, so nothing to pair with.
    recurring_days_off = db.relationship("HardCodedEventDayOff",
                                         cascade="all, delete-orphan")
    recurring_prefs    = db.relationship("ShowHardCodedEvent",
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
    sod         = db.Column(db.String(20))           # Start of Day anchor, e.g. "6:00 AM"
    eod         = db.Column(db.String(20))           # End of Day anchor,   e.g. "11:00 PM"
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
    def ordered_activities(self):
        """The day's activities BY THE CLOCK. Everything that renders a day's
        timeline must use this rather than ``activities``.

        Jason, 2026-08-11: "all schedule events need to be chronologically
        displayed." The relationship is ordered by ``sort_order``, which is
        insertion-or-drag order and drifts from the clock the moment anything
        is added out of sequence — and `place_in_day` anchors overlays against
        TIME, so the two disagreeing scattered recurring events, break periods
        and beverage touchpoints through the page.

        ``sort_order`` remains the tie-break, so two things at 08:00 keep the
        order somebody dragged them into. An activity with no readable time
        sorts last rather than pretending to be at midnight.

        Same pattern, and the same reason, as ``ScheduleActivity
        .ordered_crew_rows``.
        """
        return sorted(
            self.activities,
            key=lambda a: (time_utils.parse_minutes(a.time) is None,
                           time_utils.parse_minutes(a.time) or 0,
                           a.sort_order or 0, a.id or 0),
        )

    @property
    def day_header(self):
        if self.date:
            return self.date.strftime("%A, %B %-d, %Y")
        return "Date TBD"

    @property
    def phase_labels(self):
        """#32 — per-phase day labels for this date, e.g.
        ['Lighting Prep D2', 'Video Prep D1'], ordered by phase start date."""
        from datetime import date as _d
        dps = sorted(
            self.day_phases,
            key=lambda x: ((x.phase.start_date or _d.max) if x.phase else _d.max,
                           x.day_index or 0),
        )
        return [dp.label for dp in dps if dp.label]

    @property
    def time_window(self):
        start = self.sod or self.call_time
        end   = self.eod or self.wrap_time
        if start and end:
            return f"{start} – {end}"
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
    # The CrewBreak that DESCRIBES this activity, if it is a break.
    #
    # Added 2026-08-12 after a real 500. `crew_breaks.activity_id` is UNIQUE,
    # and without this cascade deleting a day or a show left its CrewBreak
    # rows behind pointing at activities that no longer existed. SQLite reuses
    # rowids, so the next activity created took an id an orphan still claimed
    # and the insert died on the unique constraint — a delete in one show
    # breaking a create in another, with nothing on screen to explain it.
    #
    # Scoped to `activity_id` deliberately, NOT `crew_call_id`: deleting a
    # crew call should not silently delete the breaks hanging off it, which is
    # a decision with a catering consequence and belongs in a route that can
    # say so.
    crew_break  = db.relationship("CrewBreak", uselist=False,
                                  foreign_keys="CrewBreak.activity_id",
                                  back_populates="activity",
                                  cascade="all, delete-orphan")

    @property
    def ordered_crew_rows(self):
        """Crew rows in ROSTER order, section structure preserved.

        Everything that renders a crew call must use this rather than
        ``crew_rows``. ``CrewRow.sort_order`` is insertion order, and a stored
        per-call copy of the order is precisely what drifts away from the
        roster — deriving here is what makes a roster reorder show up on every
        crew call immediately.
        """
        from crew_ordering import order_crew_rows, roster_index
        show_id = self.day.show_id if self.day else None
        rows = list(self.crew_rows)
        if not show_id:
            return rows
        return order_crew_rows(rows, roster_index(show_id))

    @property
    def crew_headcount(self):
        """How many people this one call brings in.

        Same rule as ``ScheduleDay.computed_crew_count``, scoped to a single
        activity: a named person counts once however many rows they hold, an
        unnamed row counts its ``qty`` because each is a distinct slot that
        still has to be fed. Unfilled slots ARE counted — somebody will be
        standing in that spot at lunchtime.

        This is what a catered break derives its headcount from, so it must
        never be cached: the whole point is that changing the crew changes
        what F&B is told.
        """
        named_ids = set()
        unnamed_total = 0
        for row in self.crew_rows:
            if row.is_group_header:
                continue
            if row.crew_member_id:
                named_ids.add(row.crew_member_id)
            else:
                unnamed_total += (row.qty or 1)
        return len(named_ids) + unnamed_total

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
    # Tiered sections (note 1, 2026-08-11). Larry's real headers nest: ENCORE
    # at level 1 with RIGGING, RUN CREW, LOCAL CREW beneath it. 1 = top level,
    # 2 = sub-header. Every pre-existing header is level 1, so nothing moves
    # until someone deliberately nests it.
    header_level    = db.Column(db.Integer, default=1)
    # What the section is FOR. A level-1 header bound to a company is what
    # lets a newly added person find their own section automatically; the
    # label stays free text so Larry can title it whatever he likes.
    company_id      = db.Column(db.Integer, db.ForeignKey("companies.id"),
                                nullable=True)

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
            return self.crew_member.display_label
        return self.name_override or "TBD"

    @property
    def is_unfilled(self):
        """True when this row is a called slot with nobody named in it yet.

        Drives the quiet visual marker so Larry can scan a day and see what is
        still open. Deliberately NOT excluded from headcounts — an unfilled
        slot still has to be called, fed and scheduled.
        """
        if self.is_group_header:
            return False
        if self.crew_member:
            return self.crew_member.is_unnamed_slot
        return not (self.name_override or "").strip()

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


class DayPhase(db.Model):
    """#32 — a day's membership in a production phase, with a per-phase day
    index, so a single day can belong to several overlapping phases at once
    (e.g. 'Lighting Prep Day 2' AND 'Video Prep Day 1' on the same date)."""
    __tablename__ = "day_phases"
    id        = db.Column(db.Integer, primary_key=True)
    day_id    = db.Column(db.Integer, db.ForeignKey("schedule_days.id"), nullable=False)
    phase_id  = db.Column(db.Integer, db.ForeignKey("production_phases.id"), nullable=False)
    day_index = db.Column(db.Integer, default=1)   # 1-based day number within the phase

    day   = db.relationship("ScheduleDay",
                            backref=db.backref("day_phases",
                                               cascade="all, delete-orphan"))
    phase = db.relationship("ProductionPhase",
                            backref=db.backref("day_phases",
                                               cascade="all, delete-orphan"))

    @property
    def label(self):
        return f"{self.phase.name} D{self.day_index}" if self.phase else ""


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
        """[[time, description], ...] with times normalised to 24-hour HH:MM.

        The seeded payloads store 12-hour text (["1:00 PM", "AFTERNOON
        SESSION"]). Applied verbatim, every template-created activity got a
        time that rendered as a BLANK <input type="time"> on the day page and
        sorted lexically below every 24-hour time. Normalising here fixes both
        template-application paths at once (generate-days and apply-template).
        """
        try:
            raw = json.loads(self.activities_json or "[]")
        except Exception:
            return []
        out = []
        for pair in raw:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            out.append([time_utils.hhmm_or_blank(pair[0]), pair[1]])
        return out

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
    """Return True if a ScheduleActivity looks like a meal break.

    LEGACY. Kept for shows that have not been switched to the new breaks model
    (``Show.uses_new_breaks``). Guessing catering from a description is the bug
    CrewBreak exists to fix — do not build anything new on this.
    """
    if not activity or not activity.description:
        return False
    desc = activity.description.upper()
    return any(kw in desc for kw in MEAL_KEYWORDS)


# ── Crew breaks (2026-08-11 overhaul) ────────────────────────────────────────
#
# Catering is DECLARED, not inferred from an activity's name. See the project
# doc ADI_Breaks_And_Meals_Design.md.

CATERED_YES = "yes"
CATERED_NO = "no"
CATERED_UNCONFIRMED = "unconfirmed"
CATERED_STATES = [CATERED_YES, CATERED_NO, CATERED_UNCONFIRMED]

# Re-exported from breaks.py so a model default and the rules that read it
# cannot drift into two spellings of the same word.
from breaks import KIND_COFFEE as BREAK_KIND_COFFEE  # noqa: E402
from breaks import KIND_MEAL as BREAK_KIND_MEAL      # noqa: E402


class CrewBreak(db.Model):
    """A break in a crew's shift, and whether F&B provides anything at it.

    WRAPS an existing ScheduleActivity rather than replacing it. Three tables
    point at schedule_activities — CrewRow (not-null), SubScheduleEntry and
    MealService — so replacing a break activity would cascade-delete its crew
    rows and orphan any OSS entry or meal service already linked to it. The
    activity stays the thing that exists on the timeline; this adds the
    anchoring and the catering declaration on top, and nothing is destroyed.

    ``catered`` is three-state on purpose. ``unconfirmed`` means nobody has
    said yet, and it must NEVER be read as "no" — that is how a meal quietly
    stops reaching the F&B manager. Unconfirmed breaks show on F&B flagged,
    because a missing meal on site is far worse than an extra line.
    """
    __tablename__ = "crew_breaks"
    id           = db.Column(db.Integer, primary_key=True)
    show_id      = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    # The break event itself — preserved, never replaced.
    activity_id  = db.Column(db.Integer, db.ForeignKey("schedule_activities.id"),
                             nullable=False)
    # The CREW START this break is timed from. Nullable because a legacy break
    # may not be attributable to one crew start at migration time.
    crew_call_id = db.Column(db.Integer, db.ForeignKey("schedule_activities.id"),
                             nullable=True)
    offset_minutes   = db.Column(db.Integer)
    duration_minutes = db.Column(db.Integer, default=60)
    label            = db.Column(db.String(120))
    catered          = db.Column(db.String(12), default=CATERED_UNCONFIRMED)
    # meal | coffee (2026-08-12). The ONE thing it changes is whether the
    # catering question is asked. Jason: a coffee break is "around 2.5 hours
    # after the start of the call or coming back from a meal break", it is
    # always 15 minutes, and "they just are what they are" — the crew helps
    # itself from the standing beverage table, so there is nothing to decide.
    # Stored rather than derived from the duration, so that changing a break's
    # length cannot silently strip a catering answer somebody gave.
    kind             = db.Column(db.String(12), default=BREAK_KIND_MEAL)
    meal_service_id  = db.Column(db.Integer, db.ForeignKey("meal_services.id"),
                                 nullable=True)

    show         = db.relationship("Show", back_populates="crew_breaks")
    activity     = db.relationship("ScheduleActivity", foreign_keys=[activity_id],
                                   back_populates="crew_break")
    crew_call    = db.relationship("ScheduleActivity", foreign_keys=[crew_call_id])
    # uselist=False because MealService <-> CrewBreak is 1:1 by design: one
    # service per crew group, always. Two crew groups lunching an hour apart
    # get two services, because one covering service would put food out for
    # three hours and break the 2-hour rule.
    meal_service = db.relationship(
        "MealService", backref=db.backref("crew_break", uselist=False))

    __table_args__ = (db.UniqueConstraint("activity_id", name="uq_crew_break_activity"),)

    @property
    def is_catered(self):
        """Strictly 'yes'. Unconfirmed is NOT catered and NOT uncatered."""
        return self.catered == CATERED_YES

    @property
    def needs_confirmation(self):
        return self.catered == CATERED_UNCONFIRMED

    @property
    def is_coffee(self):
        return self.kind == BREAK_KIND_COFFEE

    @property
    def asks_catering(self):
        """Does this break put a question to anybody?

        A coffee break does not. It is fifteen minutes, the crew helps itself
        from the standing beverage table, and there is nothing for F&B to
        decide — so the control is not shown and it never reaches the coverage
        panel. Asking a question with only one answer, 54 times, is how the
        real questions stop being read.
        """
        return not self.is_coffee

    @property
    def visible_to_fnb(self):
        """F&B sees catered breaks, and unconfirmed ones so they can be
        resolved. Never a break confirmed as uncatered, and never a coffee
        break — that one runs off the standing beverage service, which feeds
        nobody AT a break by definition."""
        if self.is_coffee:
            return False
        return self.catered in (CATERED_YES, CATERED_UNCONFIRMED)

    @property
    def start_minute(self):
        """When the crew actually stops, in minutes. None when unreadable.

        parse_minutes, not sort_minutes: the sentinel would place a break at
        minute 1,000,000 rather than admitting it has no time.
        """
        if self.activity is None:
            return None
        return time_utils.parse_minutes(self.activity.time)

    @property
    def end_time(self):
        """When this crew is back. '' when the start is unreadable."""
        from breaks import window_end
        return time_utils.from_minutes(
            window_end(self.start_minute, self.duration_minutes))

    @property
    def fed_headcount(self):
        """How many F&B is being asked to feed at this sitting, or None when
        nobody is feeding it."""
        svc = self.meal_service
        return svc.total_headcount if svc is not None else None

    @property
    def derived_headcount(self):
        """How many crew this break stops — read from the crew call it hangs
        off, live.

        ``None`` when there is no crew-call anchor. That is not zero: a legacy
        break with no anchor has an UNKNOWN headcount, and telling a caterer
        zero is how a crew goes unfed. Callers must show it as unknown and ask
        for a number.
        """
        if self.crew_call is None:
            return None
        return self.crew_call.crew_headcount

    def __repr__(self):
        return f"<CrewBreak {self.label!r} catered={self.catered}>"


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

    @property
    def stay_nights(self):
        """Nights on-site, derived from the shared Travel In → Travel Out
        window (the same dates shown on the Booking Sheet). The Travel page
        uses these dates for check-in/out so the two sheets stay in sync."""
        if self.travel_in_date and self.travel_out_date:
            delta = (self.travel_out_date - self.travel_in_date).days
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

    show     = db.relationship("Show", back_populates="open_slots")
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

    show           = db.relationship("Show", back_populates="oss_entries")
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


class HardCodedEvent(db.Model):
    """Global recurring events (Security, Crew Beverage Set, …) defined once and
    (Phase 2) auto-applied to every day, timed as offsets from that day's
    SOD/EOD. A department, when set, surfaces the event on that OSS tab (#35)."""
    __tablename__ = "hard_coded_events"
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    department   = db.Column(db.String(50))                 # one of SUB_SCHEDULE_TYPES, or blank
    start_anchor = db.Column(db.String(3), default="SOD")   # "SOD" | "EOD"
    start_offset = db.Column(db.Integer, default=0)         # signed minutes from anchor
    end_anchor   = db.Column(db.String(3))                  # "SOD" | "EOD" | None (point event)
    end_offset   = db.Column(db.Integer)                    # signed minutes, or None
    active       = db.Column(db.Boolean, default=True)
    sort_order   = db.Column(db.Integer, default=0)

    @staticmethod
    def _fmt(mins):
        if mins is None:
            return ""
        m = abs(int(mins))
        if not m:
            return ""
        sign = "+" if mins >= 0 else "\u2212"   # − true minus
        return f" {sign}{m // 60}:{m % 60:02d}"

    @property
    def start_label(self):
        return f"{self.start_anchor or 'SOD'}{self._fmt(self.start_offset)}"

    @property
    def end_label(self):
        if not self.end_anchor:
            return ""
        return f"{self.end_anchor}{self._fmt(self.end_offset)}"

    @property
    def is_range(self):
        return bool(self.end_anchor)

    @staticmethod
    def _offset_str(mins):
        """Signed offset for editable inputs: -60 -> '-1:00', 30 -> '+0:30', 0/None -> ''."""
        if not mins:
            return ""
        m = abs(int(mins))
        return f"{'-' if mins < 0 else '+'}{m // 60}:{m % 60:02d}"

    @property
    def start_offset_str(self):
        return self._offset_str(self.start_offset)

    @property
    def end_offset_str(self):
        return self._offset_str(self.end_offset)

    def __repr__(self):
        return f"<HardCodedEvent {self.name} {self.start_label}>"


class HardCodedEventDayOff(db.Model):
    """One occurrence of a recurring event, removed from one day of one show.

    The calendar-app model (notes 6+7, 2026-08-11): the definition is the
    series and this is a per-occurrence exception. Editing the series updates
    every occurrence still showing but does NOT resurrect hidden ones — the
    alternative is that a typo fix silently puts back an event the user
    deliberately removed from a dark day.

    Keyed on the DATE, not on ScheduleDay.id. #32 regenerates day rows from
    phase ranges, so a row id can vanish and be reissued; a suppression keyed
    on it would evaporate, or worse, reattach to a different day.
    """
    __tablename__ = "hard_coded_event_days_off"
    id      = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    hce_id  = db.Column(db.Integer, db.ForeignKey("hard_coded_events.id"),
                        nullable=False)
    date    = db.Column(db.Date, nullable=False)
    __table_args__ = (db.UniqueConstraint("show_id", "hce_id", "date",
                                          name="uq_hce_day_off"),)


class ShowHardCodedEvent(db.Model):
    """Per-show on/off for a global HardCodedEvent (#37 Phase 2). A missing row
    means the event applies (default on); a row with enabled=False turns it off
    for that show."""
    __tablename__ = "show_hard_coded_events"
    id      = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    hce_id  = db.Column(db.Integer, db.ForeignKey("hard_coded_events.id"), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    __table_args__ = (db.UniqueConstraint("show_id", "hce_id", name="uq_show_hce"),)



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

    show    = db.relationship("Show", back_populates="radio_channels")

    def __repr__(self):
        return f"<RadioChannel show={self.show_id} slot={self.slot} '{self.name or ''}'>"


class ShowCommChannel(db.Model):
    """A single COMS channel defined for a show (e.g. 'Main', 'LX', 'Cam')."""
    __tablename__ = "show_comm_channels"
    id         = db.Column(db.Integer, primary_key=True)
    show_id    = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=False)
    name       = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    show       = db.relationship("Show", back_populates="comm_channels")

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

    show            = db.relationship("Show", back_populates="comm_assignments")
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

# "meal" leads because it is now the common case: a break is a MEAL BREAK
# (2026-08-12) and the first one is not always lunch. The specific kinds stay
# — a caterer told "breakfast" knows more than one told "meal" — but nothing
# has to pretend a midday meal is lunch to avoid landing in "other".
MEAL_KINDS = ["meal", "breakfast", "lunch", "dinner", "beverages", "snack",
              "other"]


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
    # Service window (2026-08-11). F&B is set up before the crew breaks and
    # holds for latecomers after, so a catered meal is ONE event with TWO
    # times: crew surfaces show the break, F&B surfaces show the window.
    # House defaults confirmed by Jason: 30 before, 1 hour service, 30 after.
    setup_minutes     = db.Column(db.Integer, default=30)
    holdover_minutes  = db.Column(db.Integer, default=30)
    # Standing beverage service only (2026-08-11). Set up relative to the
    # day's SOD by an amount chosen when the service is created — NOT off the
    # first crew call, which was the earlier guess — and refreshed on its own
    # interval. Negative offset means "before SOD".
    beverage_offset_minutes   = db.Column(db.Integer, default=-30)
    beverage_interval_minutes = db.Column(db.Integer, default=150)
    # "This service feeds no crew break, and that is the right answer."
    # (2026-08-12, step 6.) The F&B tab has always OFFERED standalone as an
    # answer to the Feeds question — a client lunch or a green room genuinely
    # feeds nobody — but had nowhere to record it, so the answer was
    # indistinguishable from never having been asked. The coverage panel needs
    # that difference: a check that cannot reach zero is the next warning
    # nobody reads. Cleared automatically the moment the service is linked.
    standalone_confirmed = db.Column(db.Boolean, default=False)

    show            = db.relationship("Show", back_populates="meal_services")
    schedule_day    = db.relationship("ScheduleDay")
    linked_activity = db.relationship("ScheduleActivity")
    locations       = db.relationship("MealServiceLocation",
                                      back_populates="meal_service",
                                      order_by="MealServiceLocation.sort_order, MealServiceLocation.id",
                                      cascade="all, delete-orphan")

    @property
    def derived_headcount(self):
        """The crew this service feeds, read live off the break's crew call.

        ``None`` when the service is not anchored to a break — a standalone
        service has nothing to derive from and must be given a number.
        """
        cb = getattr(self, "crew_break", None)
        return cb.derived_headcount if cb is not None else None

    @property
    def total_headcount(self):
        """What F&B is being asked to feed.

        Reads EFFECTIVE figures, so a service nobody has typed numbers into
        still reports the crew it feeds, and keeps reporting the right one
        after the crew changes.
        """
        return sum((loc.effective_headcount or 0) for loc in self.locations)

    @property
    def headcount_is_derived(self):
        """True when no location carries a hand-typed figure, i.e. the total
        is following the crew."""
        return (self.derived_headcount is not None
                and all(loc.headcount is None for loc in self.locations))

    @property
    def locations_ordered(self):
        """Locations in clock order. The `locations` relationship is ordered by
        sort_order (assigned at creation), so a location added later sat at the
        bottom regardless of its start_time."""
        return sorted(
            self.locations,
            key=lambda loc: (time_utils.sort_minutes(loc.start_time),
                             loc.sort_order or 0, loc.id or 0),
        )

    @property
    def earliest_time(self):
        """Earliest start_time across locations (for sorting/display).

        Compared as minutes, not as text: '9:00 AM' loses a string compare to
        '10:00 AM' even though it is earlier."""
        return time_utils.earliest(
            [loc.start_time for loc in self.locations if loc.start_time])

    @property
    def is_linked(self):
        return self.activity_id is not None

    @property
    def is_standing(self):
        """All-day beverages: F&B sets up and tops up through the day, and the
        crew never stops for it. Not a break, not a point-in-time meal."""
        return bool(self.is_recurring)

    @property
    def beverage_plan(self):
        """Setup and refresh touchpoints for a standing service, computed.

        Never stored: they move with the first crew call, the day's EOD and
        who is on site. Returns None for an ordinary service, and a plan
        carrying a `reason` rather than an empty list when the day cannot
        support touchpoints.
        """
        if not self.is_standing:
            return None
        from beverage_service import plan_for_service
        return plan_for_service(self)

    def __repr__(self):
        return f"<MealService {self.name} day={self.schedule_day_id}>"


class MealServiceLocation(db.Model):
    __tablename__ = "meal_service_locations"
    id              = db.Column(db.Integer, primary_key=True)
    meal_service_id = db.Column(db.Integer, db.ForeignKey("meal_services.id"), nullable=False)
    location_name   = db.Column(db.String(200))   # "Backstage", "FOH MainStage", ...
    start_time      = db.Column(db.String(20))    # "HH:MM"
    end_time        = db.Column(db.String(20))
    # The HAND-TYPED figure, and nothing else. NULL means "follow the crew".
    #
    # Read `effective_headcount` to display or export a number; read this one
    # only to fill an input's value=, where blank has to mean "not overridden"
    # so that clearing the box reverts to the derived figure. Every value in
    # here before 2026-08-11 was typed by hand, which is exactly what an
    # override is, so no data had to move.
    headcount       = db.Column(db.Integer)
    notes           = db.Column(db.Text)
    sort_order      = db.Column(db.Integer, default=0)

    meal_service    = db.relationship("MealService", back_populates="locations")

    @property
    def is_overridden(self):
        return self.headcount is not None

    @property
    def derived_headcount(self):
        """This location's share of the crew, when nobody has typed a figure.

        A service with ONE location feeds it the whole crew — the ordinary
        case, and unambiguous.

        With several, the app will not invent a split it cannot know. What the
        typed locations have claimed comes off the top and the balance goes to
        the FIRST location without a typed figure; any further untyped
        location reads 0. So two locations, crew of 20, one typed as 12 — the
        other shows 8, and both move when the crew call changes.

        ``None`` when there is nothing to derive from.
        """
        svc = self.meal_service
        if svc is None:
            return None
        total = svc.derived_headcount
        if total is None:
            return None
        siblings = list(svc.locations)
        if len(siblings) <= 1:
            return total
        # Self is excluded from `claimed` so this answers the same question
        # whether or not a figure has been typed here: what the crew call
        # gives THIS location.
        claimed = sum(loc.headcount or 0 for loc in siblings
                      if loc.is_overridden and loc is not self)
        candidates = [loc for loc in siblings
                      if loc is self or not loc.is_overridden]
        if candidates and candidates[0] is not self:
            return 0
        return max(0, total - claimed)

    @property
    def effective_headcount(self):
        """The number to show and to export. Typed figure wins; otherwise the
        crew is followed."""
        if self.headcount is not None:
            return self.headcount
        return self.derived_headcount

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

    show       = db.relationship("Show", back_populates="dietary_notes")

    def __repr__(self):
        return f"<ShowDietaryNote {self.preference} show={self.show_id}>"



# ── Undo/Redo audit log ──────────────────────────────────────────────────────
#
# Every INSERT / UPDATE / DELETE on a tracked model writes an entry here.
# The full row state before + after each change is stored as JSON so an
# undo can restore the exact prior value, and a redo can re-apply.
#
# Rows are grouped by `group_id` (one UUID per HTTP request) so a single
# user action that cascades — e.g. deleting a ScheduleDay which cascades
# to its Activities and CrewRows — can be undone as a unit.
#
# `undone=True` means the change has been reversed. Redo flips it back
# to False.

AUDIT_TRACKED_TABLES = [
    "schedule_days",
    "schedule_activities",
    "crew_rows",
    "show_crew_assignments",
    "show_open_slots",
    "sub_schedule_entries",
    "meal_services",
    "meal_service_locations",
    "show_dietary_notes",
    "shows",
    "production_phases",
    "requests",
    "request_attachments",
]


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id           = db.Column(db.Integer, primary_key=True)
    group_id     = db.Column(db.String(36), index=True)   # UUID per request
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    table_name   = db.Column(db.String(80), nullable=False, index=True)
    row_id       = db.Column(db.Integer, nullable=False)
    action       = db.Column(db.String(10), nullable=False)   # insert / update / delete
    before_json  = db.Column(db.Text)   # NULL for insert
    after_json   = db.Column(db.Text)   # NULL for delete
    undone       = db.Column(db.Boolean, default=False, index=True)
    request_path = db.Column(db.String(200))
    label        = db.Column(db.String(200))   # optional human-readable summary

    def __repr__(self):
        return (f"<AuditLog {self.action} {self.table_name}#{self.row_id} "
                f"undone={self.undone}>")



# ── Feature / bug request board ──────────────────────────────────────────────
#
# Replaces the "ADI Build Notes" Google Doc so Jason and Larry can track
# feature requests, bug reports, and their status from inside the app.

REQUEST_PRIORITIES = ["P0", "P1", "P2", "P3"]
REQUEST_STATUSES   = ["requested", "in_progress", "ready_to_test",
                      "deployed", "deferred"]
REQUEST_CATEGORIES = ["bug", "feature", "ux", "question"]

REQUEST_STATUS_LABELS = {
    "requested":     "Requested",
    "in_progress":   "In Progress",
    "ready_to_test": "Ready to Test",
    "deployed":      "Deployed",
    "deferred":      "Deferred",
}


class Request(db.Model):
    __tablename__ = "requests"
    id            = db.Column(db.Integer, primary_key=True)
    title         = db.Column(db.String(300), nullable=False)
    description   = db.Column(db.Text)
    category      = db.Column(db.String(20), default="feature")   # bug/feature/ux/question
    priority      = db.Column(db.String(5),  default="P2")        # P0/P1/P2/P3
    status        = db.Column(db.String(20), default="requested")
    requested_by  = db.Column(db.String(80))                      # freetext (Larry / Jason / ...)
    notes         = db.Column(db.Text)                            # ongoing comments
    commit_ref    = db.Column(db.String(50))                      # optional commit sha
    sort_order    = db.Column(db.Integer, default=0)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow,
                              onupdate=datetime.utcnow)
    deployed_at   = db.Column(db.DateTime)

    attachments   = db.relationship(
        "RequestAttachment",
        backref="request",
        cascade="all, delete-orphan",
        order_by="RequestAttachment.uploaded_at.asc()",
    )

    def __repr__(self):
        return f"<Request #{self.id} {self.status} '{self.title[:40]}'>"


class RequestAttachment(db.Model):
    """Image attachment on a Request — typically a bug-report screenshot."""
    __tablename__ = "request_attachments"
    id              = db.Column(db.Integer, primary_key=True)
    request_id      = db.Column(db.Integer,
                                db.ForeignKey("requests.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    filename        = db.Column(db.String(300))          # original client filename
    stored_filename = db.Column(db.String(80))           # server-side UUID.ext
    content_type    = db.Column(db.String(80))           # e.g. image/png
    size_bytes      = db.Column(db.Integer)
    uploaded_at     = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by     = db.Column(db.String(80))           # optional, freetext

    def __repr__(self):
        return f"<RequestAttachment #{self.id} req#{self.request_id} {self.filename}>"



class AgencySetting(db.Model):
    """Singleton row holding the agency's own branding.

    Separate from per-show artwork (#48): the show artwork is the client's
    key art, this is ADI Productions' own mark. Both appear on generated
    paperwork and on the Master OSS exports. Stored as a row rather than a
    constant so the logo can be swapped without a deploy — and so board #49
    (agency artwork on RFPs) has something to read from.
    """
    __tablename__ = "agency_settings"
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(200), default="ADI Productions")
    logo_filename = db.Column(db.String(300))
    # Midnight, the ADI primary. See brand.py — sourced from Larry's brand
    # token file, not sampled from artwork as the previous default was.
    primary_hex   = db.Column(db.String(7), default=brand.PRIMARY)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow,
                              onupdate=datetime.utcnow)

    @classmethod
    def get(cls):
        """The one row, created on first access."""
        row = cls.query.order_by(cls.id).first()
        if row is None:
            row = cls()
            db.session.add(row)
            db.session.commit()
        return row

    def __repr__(self):
        return f"<AgencySetting {self.name} logo={self.logo_filename}>"
