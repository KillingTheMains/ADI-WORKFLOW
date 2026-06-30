"""
Crew bulk-import blueprint.

Flow:
  1. POST /crew/import/upload        — user picks an .xlsx, server parses,
                                       matches each row against existing crew,
                                       and creates a CrewImportSession holding
                                       the parsed rows + match info.
  2. GET  /crew/import/<sid>/preview — preview page lets the user choose
                                       add / update / skip per row, and
                                       resolve unknown positions / companies.
  3. POST /crew/import/<sid>/commit  — applies the decisions, returns to
                                       the roster with a summary flash.
  4. POST /crew/import/<sid>/cancel  — discards the session.

Matching is by email first, then first+last+company (case-insensitive).
Update mode is "fill blanks only" — never overwrite existing values.
Conflicting fields are surfaced for per-row decision.
"""
import io
import json
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from extensions import db
from models import (CrewMember, Position, Company, CrewImportSession)

crew_import_bp = Blueprint("crew_import", __name__)


# ── Column aliases (XLSX headers we accept) ──────────────────────────────────
# Lower-case + stripped before lookup. The first match wins.
COLUMN_ALIASES = {
    "first_name": ["first name", "first", "firstname", "first_name", "given name", "given"],
    "last_name":  ["last name", "last", "lastname", "last_name", "surname", "family name"],
    "email":      ["email", "e-mail", "email address", "e mail"],
    "phone":      ["phone", "phone number", "mobile", "cell", "tel", "telephone"],
    "position":   ["position", "title", "role", "job title", "job", "position/title"],
    "company":    ["company", "vendor", "employer", "organization", "org", "business"],
}


def _normalize_header(h):
    return (h or "").strip().lower().replace("_", " ")


def _map_columns(header_row):
    """Return {our_field: col_index} based on the alias table."""
    mapping = {}
    for idx, raw in enumerate(header_row):
        norm = _normalize_header(str(raw) if raw is not None else "")
        for field, aliases in COLUMN_ALIASES.items():
            if field in mapping:
                continue
            if norm in aliases:
                mapping[field] = idx
                break
    return mapping


def _parse_xlsx(file_storage):
    """Parse the uploaded XLSX into a list of row dicts. Raises ValueError on bad input."""
    try:
        import openpyxl
    except ImportError:
        raise ValueError("openpyxl is not installed on the server. Run: pip install openpyxl")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_storage.read()), data_only=True)
    except Exception as e:
        raise ValueError(f"Couldn't open the file as XLSX: {e}")
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("The spreadsheet is empty.")

    header = rows[0]
    mapping = _map_columns(header)
    if "first_name" not in mapping or "last_name" not in mapping:
        raise ValueError(
            "Couldn't find First Name + Last Name columns. "
            f"Found headers: {[str(h) for h in header if h is not None]}"
        )

    out = []
    for i, row in enumerate(rows[1:], start=2):  # data starts on row 2
        rec = {"n": i}
        for field, col_idx in mapping.items():
            if col_idx < len(row):
                val = row[col_idx]
                rec[field] = (str(val).strip() if val is not None else "")
            else:
                rec[field] = ""
        # Skip totally-empty rows (no first AND no last)
        if not rec.get("first_name") and not rec.get("last_name"):
            continue
        out.append(rec)
    return out



# ── Matching against existing crew ───────────────────────────────────────────

def _enrich_with_match_info(rec, all_crew_by_email, all_crew_by_namekey,
                            all_positions_by_title, all_companies_by_name):
    """Decorate a parsed row with matched_id, fillable_fields, conflicts, and
    position/company action."""
    email = (rec.get("email") or "").strip().lower()
    first = (rec.get("first_name") or "").strip().lower()
    last  = (rec.get("last_name") or "").strip().lower()
    co    = (rec.get("company") or "").strip().lower()

    match = None
    reason = None
    if email and email in all_crew_by_email:
        match = all_crew_by_email[email]
        reason = "email"
    else:
        key = (first, last, co)
        if all(key) and key in all_crew_by_namekey:
            match = all_crew_by_namekey[key]
            reason = "name+company"

    rec["matched_id"]   = match.id if match else None
    rec["match_reason"] = reason
    rec["fillable_fields"] = []
    rec["conflicts"]       = {}

    if match:
        # Email
        ev = (rec.get("email") or "").strip()
        if ev:
            if not (match.email or "").strip():
                rec["fillable_fields"].append("email")
            elif ev.lower() != match.email.lower():
                rec["conflicts"]["email"] = [match.email, ev]
        # Phone
        pv = (rec.get("phone") or "").strip()
        if pv:
            if not (match.phone or "").strip():
                rec["fillable_fields"].append("phone")
            elif pv != match.phone:
                rec["conflicts"]["phone"] = [match.phone, pv]
        # Position (compare by title since file has free-text)
        posv = (rec.get("position") or "").strip()
        if posv:
            cur_title = match.position.title if match.position else ""
            if not cur_title:
                rec["fillable_fields"].append("position")
            elif posv.lower() != cur_title.lower():
                rec["conflicts"]["position"] = [cur_title, posv]
        # Company
        cov = (rec.get("company") or "").strip()
        if cov:
            cur_co = match.company.name if match.company else ""
            if not cur_co:
                rec["fillable_fields"].append("company")
            elif cov.lower() != cur_co.lower():
                rec["conflicts"]["company"] = [cur_co, cov]

    # Position lookup status (lets us prompt "new" in preview)
    posv = (rec.get("position") or "").strip()
    if not posv:
        rec["position_action"] = "missing"
    elif posv.lower() in all_positions_by_title:
        rec["position_action"] = "exact"
    else:
        rec["position_action"] = "new"

    cov = (rec.get("company") or "").strip()
    if not cov:
        rec["company_action"] = "missing"
    elif cov.lower() in all_companies_by_name:
        rec["company_action"] = "exact"
    else:
        rec["company_action"] = "new"

    return rec



# ── Routes ───────────────────────────────────────────────────────────────────

@crew_import_bp.route("/import/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Please pick a file first.", "danger")
        return redirect(url_for("crew.index"))

    if not f.filename.lower().endswith((".xlsx", ".xlsm")):
        flash("Only .xlsx files are supported for now. (PDF coming later.)", "danger")
        return redirect(url_for("crew.index"))

    try:
        parsed = _parse_xlsx(f)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("crew.index"))

    if not parsed:
        flash("No usable rows found in the file (need at least First + Last name).", "warning")
        return redirect(url_for("crew.index"))

    # Pre-load existing crew + positions + companies for matching
    all_crew = CrewMember.query.all()
    by_email    = {(c.email or "").strip().lower(): c
                   for c in all_crew if (c.email or "").strip()}
    by_namekey  = {
        ((c.first_name or "").strip().lower(),
         (c.last_name  or "").strip().lower(),
         (c.company.name or "").strip().lower() if c.company else ""): c
        for c in all_crew
    }
    by_pos      = {p.title.strip().lower(): p
                   for p in Position.query.all() if p.title}
    by_co       = {c.name.strip().lower(): c
                   for c in Company.query.all() if c.name}

    enriched = [_enrich_with_match_info(r, by_email, by_namekey, by_pos, by_co)
                for r in parsed]

    session = CrewImportSession(filename=f.filename)
    session.rows = enriched
    db.session.add(session)
    db.session.commit()

    return redirect(url_for("crew_import.preview", sid=session.id))


@crew_import_bp.route("/import/<int:sid>/preview")
def preview(sid):
    session = CrewImportSession.query.get_or_404(sid)
    if session.status != "pending":
        flash(f"This import session has already been {session.status}.", "info")
        return redirect(url_for("crew.index"))

    rows = session.rows
    # Suggested defaults for the per-row Decision dropdown
    for r in rows:
        if not r.get("matched_id"):
            r["suggested"] = "add"
        elif r.get("conflicts"):
            r["suggested"] = "conflict"   # user picks manually
        elif r.get("fillable_fields"):
            r["suggested"] = "update"
        else:
            r["suggested"] = "skip"       # exact duplicate

    summary = {
        "total":   len(rows),
        "add":     sum(1 for r in rows if r["suggested"] == "add"),
        "update":  sum(1 for r in rows if r["suggested"] == "update"),
        "skip":    sum(1 for r in rows if r["suggested"] == "skip"),
        "conflict":sum(1 for r in rows if r["suggested"] == "conflict"),
        "new_pos": sum(1 for r in rows if r.get("position_action") == "new"),
        "new_co":  sum(1 for r in rows if r.get("company_action") == "new"),
    }

    # For "map to existing" dropdowns
    all_positions = Position.query.order_by(Position.department, Position.title).all()
    all_companies = Company.query.order_by(Company.name).all()

    return render_template("crew/import_preview.html",
                           session=session, rows=rows, summary=summary,
                           all_positions=all_positions, all_companies=all_companies)



def _resolve_position(row, form):
    """
    Return a Position object (or None) based on the user's per-row choice.
    Form fields used:  pos_choice_<n>  ('create' | 'map' | 'skip')
                       pos_map_<n>     (existing position id when choice=map)
    """
    title = (row.get("position") or "").strip()
    if not title:
        return None
    n = row["n"]
    choice = (form.get(f"pos_choice_{n}") or "").strip()
    if not choice:
        # No per-row choice → default by action
        choice = "use" if row.get("position_action") == "exact" else "skip"

    if choice == "use" or row.get("position_action") == "exact":
        # Exact existing match
        existing = Position.query.filter(
            db.func.lower(Position.title) == title.lower()
        ).first()
        if existing:
            return existing
    if choice == "map":
        mid = form.get(f"pos_map_{n}", "").strip()
        if mid.isdigit():
            return Position.query.get(int(mid))
    if choice == "create":
        existing = Position.query.filter(
            db.func.lower(Position.title) == title.lower()
        ).first()
        if existing:
            return existing
        p = Position(title=title)
        db.session.add(p)
        db.session.flush()   # populate p.id
        return p
    return None  # skip


def _resolve_company(row, form):
    name = (row.get("company") or "").strip()
    if not name:
        return None
    n = row["n"]
    choice = (form.get(f"co_choice_{n}") or "").strip()
    if not choice:
        choice = "use" if row.get("company_action") == "exact" else "skip"

    if choice == "use" or row.get("company_action") == "exact":
        existing = Company.query.filter(
            db.func.lower(Company.name) == name.lower()
        ).first()
        if existing:
            return existing
    if choice == "map":
        cid = form.get(f"co_map_{n}", "").strip()
        if cid.isdigit():
            return Company.query.get(int(cid))
    if choice == "create":
        existing = Company.query.filter(
            db.func.lower(Company.name) == name.lower()
        ).first()
        if existing:
            return existing
        c = Company(name=name)
        db.session.add(c)
        db.session.flush()
        return c
    return None


@crew_import_bp.route("/import/<int:sid>/commit", methods=["POST"])
def commit(sid):
    session = CrewImportSession.query.get_or_404(sid)
    if session.status != "pending":
        flash(f"Already {session.status}.", "info")
        return redirect(url_for("crew.index"))

    form = request.form
    rows = session.rows
    counts = {"added": 0, "updated": 0, "skipped": 0, "errors": 0}
    errors = []

    for row in rows:
        n = row["n"]
        # User-chosen action — falls back to the suggested one
        action = (form.get(f"decision_{n}") or "").strip() or row.get("suggested") or "skip"

        try:
            # Don't resolve position/company until we know we'll actually
            # use them — otherwise a "skip" action would still create the
            # new master-list entries the user picked in the dropdown.
            if action == "skip":
                counts["skipped"] += 1
                row["decision"] = "skip"
                continue

            position = _resolve_position(row, form)
            company  = _resolve_company(row, form)

            if action == "add":
                if not (row.get("first_name") and row.get("last_name")):
                    raise ValueError("first and last name required")
                cm = CrewMember(
                    first_name = row["first_name"].strip(),
                    last_name  = row["last_name"].strip(),
                    email      = (row.get("email")  or "").strip() or None,
                    phone      = (row.get("phone")  or "").strip() or None,
                    position_id= position.id if position else None,
                    company_id = company.id  if company  else None,
                    active     = True,
                )
                db.session.add(cm)
                counts["added"] += 1
                row["decision"] = "add"
                continue

            if action == "update":
                if not row.get("matched_id"):
                    raise ValueError("update chosen but no existing match")
                cm = CrewMember.query.get(row["matched_id"])
                if not cm:
                    raise ValueError("matched crew member no longer exists")
                # Fill blanks only
                if not (cm.email or "").strip() and (row.get("email") or "").strip():
                    cm.email = row["email"].strip()
                if not (cm.phone or "").strip() and (row.get("phone") or "").strip():
                    cm.phone = row["phone"].strip()
                if not cm.position_id and position:
                    cm.position_id = position.id
                if not cm.company_id and company:
                    cm.company_id = company.id
                # Per-field conflict overrides (checkbox `overwrite_<n>_<field>`)
                for field in ("email", "phone"):
                    if form.get(f"overwrite_{n}_{field}") == "1":
                        v = (row.get(field) or "").strip()
                        if v:
                            setattr(cm, field, v)
                if form.get(f"overwrite_{n}_position") == "1" and position:
                    cm.position_id = position.id
                if form.get(f"overwrite_{n}_company") == "1" and company:
                    cm.company_id = company.id
                counts["updated"] += 1
                row["decision"] = "update"
                continue

            # action == "conflict" but no per-row decision made → skip
            counts["skipped"] += 1
            row["decision"] = "skip"

        except Exception as e:
            counts["errors"] += 1
            errors.append(f"Row {n}: {e}")
            row["decision"] = "error"

    db.session.commit()
    session.rows = rows
    session.status = "applied"
    session.summary = json.dumps({"counts": counts, "errors": errors})
    db.session.commit()

    msg = (f"Import complete — added {counts['added']}, "
           f"updated {counts['updated']}, skipped {counts['skipped']}"
           + (f", errors {counts['errors']}" if counts['errors'] else "") + ".")
    flash(msg, "success" if counts["errors"] == 0 else "warning")
    for e in errors[:5]:
        flash(e, "danger")
    return redirect(url_for("crew.index"))


@crew_import_bp.route("/import/<int:sid>/cancel", methods=["POST"])
def cancel(sid):
    session = CrewImportSession.query.get_or_404(sid)
    if session.status == "pending":
        session.status = "cancelled"
        db.session.commit()
    flash("Import cancelled.", "info")
    return redirect(url_for("crew.index"))
