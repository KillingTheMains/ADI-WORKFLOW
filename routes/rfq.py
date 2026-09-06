"""Vendor RFQ exports (capture log #12) and the Google connection behind the
Sheets button (capture log #13 — dormant until configured).

/shows/<id>/rfq                      the picker: one card per vendor
/shows/<id>/rfq/<vendor>.xlsx        the workbook, downloaded
/shows/<id>/rfq/<vendor>/sheet       POST — the same workbook, into Drive as
                                     a Google Sheet (needs Google configured
                                     AND connected)
/google/connect  /google/callback  /google/disconnect
"""
import datetime as dt

from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, session, url_for)

from extensions import db
from models import Show, AgencySetting, GoogleCredential
import google_sheets
import rfq_export

rfq_bp = Blueprint("rfq", __name__)


def _bucket_or_404(show, key):
    buckets = rfq_export.lines_by_vendor(show)
    if key == rfq_export.UNASSIGNED:
        b = buckets.get(rfq_export.UNASSIGNED)
    else:
        b = buckets.get(int(key)) if key.isdigit() else None
    if b is None:
        abort(404)
    return b


@rfq_bp.route("/shows/<int:show_id>/rfq")
def picker(show_id):
    show = Show.query.get_or_404(show_id)
    buckets = rfq_export.lines_by_vendor(show)
    cards = []
    for key, b in buckets.items():
        cards.append({"key": str(key), "vendor": b["vendor"], "job_number": b["job_number"],
                      "summary": rfq_export.summary(b),
                      "departments": sorted({l["department"] for l in b["lines"]},
                                            key=lambda d: rfq_export.DEPARTMENT_ORDER.index(d)
                                            if d in rfq_export.DEPARTMENT_ORDER else 99)})
    return render_template("shows/rfq.html", show=show, cards=cards,
                           google_configured=google_sheets.is_configured(),
                           google=GoogleCredential.current() if google_sheets.is_configured() else None)


@rfq_bp.route("/shows/<int:show_id>/rfq/<key>.xlsx")
def download(show_id, key):
    show = Show.query.get_or_404(show_id)
    bucket = _bucket_or_404(show, key)
    today = dt.date.today()
    wb = rfq_export.build_workbook(show, bucket, agency=AgencySetting.get(), issue_date=today)
    data = rfq_export.workbook_bytes(wb)
    name = rfq_export.filename_for(show, bucket, today)
    return Response(data, mimetype=rfq_export_mime(),
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def rfq_export_mime():
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@rfq_bp.route("/shows/<int:show_id>/rfq/<key>/sheet", methods=["POST"])
def to_sheet(show_id, key):
    if not google_sheets.is_configured():
        abort(404)
    cred = GoogleCredential.current()
    if cred is None:
        flash("Connect Google first — the button is on this page.", "warning")
        return redirect(url_for("rfq.picker", show_id=show_id))
    show = Show.query.get_or_404(show_id)
    bucket = _bucket_or_404(show, key)
    today = dt.date.today()
    wb = rfq_export.build_workbook(show, bucket, agency=AgencySetting.get(), issue_date=today)
    name = rfq_export.filename_for(show, bucket, today)
    try:
        created = google_sheets.publish_rfq(cred.refresh_token, show.code or show.name,
                                            name, rfq_export.workbook_bytes(wb))
    except Exception as e:  # the whole point of a flash: Larry sees why
        flash(f"Google would not take the sheet: {e}", "danger")
        return redirect(url_for("rfq.picker", show_id=show_id))
    link = created.get("webViewLink") or ""
    flash(f'RFQ is in Drive as a Google Sheet: <a href="{link}" target="_blank">{created.get("name")}</a>',
          "success")
    return redirect(url_for("rfq.picker", show_id=show_id))


# ── Google connection ────────────────────────────────────────────────────────

def _redirect_uri():
    return url_for("rfq.google_callback", _external=True)


@rfq_bp.route("/google/connect")
def google_connect():
    if not google_sheets.is_configured():
        abort(404)
    state = google_sheets.new_state()
    session["google_oauth_state"] = state
    session["google_oauth_next"] = request.args.get("next") or url_for("main.dashboard")
    return redirect(google_sheets.authorize_url(_redirect_uri(), state))


@rfq_bp.route("/google/callback")
def google_callback():
    if not google_sheets.is_configured():
        abort(404)
    nxt = session.pop("google_oauth_next", None) or url_for("main.dashboard")
    if request.args.get("error"):
        flash(f"Google said no: {request.args['error']}", "warning")
        return redirect(nxt)
    if request.args.get("state") != session.pop("google_oauth_state", None):
        flash("That Google sign-in did not start here. Try Connect Google again.", "danger")
        return redirect(nxt)
    tok = google_sheets.exchange_code(request.args.get("code", ""), _redirect_uri())
    refresh = tok.get("refresh_token")
    if not refresh:
        flash("Google did not return a refresh token. Disconnect the app in your Google "
              "account and connect again.", "danger")
        return redirect(nxt)
    email = ""
    try:
        email = google_sheets.account_email(tok.get("access_token", ""))
    except Exception:
        pass
    GoogleCredential.replace(refresh, email)
    flash(f"Google connected{(' as ' + email) if email else ''}. Exports go to that Drive.", "success")
    return redirect(nxt)


@rfq_bp.route("/google/disconnect", methods=["POST"])
def google_disconnect():
    if not google_sheets.is_configured():
        abort(404)
    GoogleCredential.query.delete()
    db.session.commit()
    flash("Google disconnected. Exports stay as .xlsx downloads until it is connected again.", "info")
    return redirect(request.form.get("next") or url_for("main.dashboard"))
