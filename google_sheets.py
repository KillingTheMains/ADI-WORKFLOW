"""Google Drive / Sheets export — built 2026-09-06, DORMANT until configured.

Jason's decisions (2026-09-06): exports go straight to Google Sheets, into
Larry's Drive (`larry@adiexpgroup.com`), via OAuth — Larry clicks "Connect
Google" once and the app keeps a refresh token. Folder: `01 - RFQs`, a
subfolder per show. A new Sheet every export, never updated in place.
Sharing: anyone with the link can edit, so a vendor fills the blue cells
without a Google account.

The Google Cloud project (consent screen, client id/secret) is Larry's and
ADI's to create, later. Until `GOOGLE_OAUTH_CLIENT_ID` and
`GOOGLE_OAUTH_CLIENT_SECRET` are set in the environment nothing here is
reachable: `is_configured()` is False, the buttons do not render, and the
routes answer 404. Setting the two variables is the whole switch-on.

Stdlib only (urllib) — no new dependency for a feature that is switched
off. Every HTTP call goes through `_http`, which tests replace.
"""
import base64
import json
import os
import secrets
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"
# drive.file: only files this app creates. userinfo.email: to say whose
# Drive is connected on the settings page.
SCOPES = ("https://www.googleapis.com/auth/drive.file "
          "https://www.googleapis.com/auth/userinfo.email")
RFQ_FOLDER = "01 - RFQs"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def client_id():
    return (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()


def client_secret():
    return (os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()


def is_configured():
    """Both halves of the OAuth client are present. The single switch."""
    return bool(client_id() and client_secret())


# ── transport ────────────────────────────────────────────────────────────────

def _http(method, url, data=None, headers=None, content_type=None):
    """One small HTTP function so tests can replace it. Returns parsed JSON."""
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        elif content_type == "application/x-www-form-urlencoded":
            body = urllib.parse.urlencode(data).encode()
        else:
            body = json.dumps(data).encode()
            content_type = content_type or "application/json"
        if content_type:
            hdrs["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    return json.loads(raw.decode() or "{}")


# ── OAuth ────────────────────────────────────────────────────────────────────

def authorize_url(redirect_uri, state):
    params = {
        "client_id": client_id(), "redirect_uri": redirect_uri,
        "response_type": "code", "scope": SCOPES, "access_type": "offline",
        "prompt": "consent", "include_granted_scopes": "true", "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def new_state():
    return secrets.token_urlsafe(24)


def exchange_code(code, redirect_uri):
    """code -> {access_token, refresh_token, ...}"""
    return _http("POST", TOKEN_URL, {
        "code": code, "client_id": client_id(), "client_secret": client_secret(),
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }, content_type="application/x-www-form-urlencoded")


def access_token(refresh_token):
    tok = _http("POST", TOKEN_URL, {
        "refresh_token": refresh_token, "client_id": client_id(),
        "client_secret": client_secret(), "grant_type": "refresh_token",
    }, content_type="application/x-www-form-urlencoded")
    return tok["access_token"]


def account_email(token):
    return _http("GET", USERINFO, headers={"Authorization": "Bearer " + token}).get("email", "")


# ── Drive ────────────────────────────────────────────────────────────────────

def _auth(token):
    return {"Authorization": "Bearer " + token}


def find_or_create_folder(token, name, parent_id=None):
    q = (f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and mimeType = '{FOLDER_MIME}' "
         f"and trashed = false")
    if parent_id:
        q += f" and '{parent_id}' in parents"
    url = DRIVE_FILES + "?" + urllib.parse.urlencode({"q": q, "fields": "files(id,name)", "pageSize": 5})
    found = _http("GET", url, headers=_auth(token)).get("files") or []
    if found:
        return found[0]["id"]
    meta = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        meta["parents"] = [parent_id]
    return _http("POST", DRIVE_FILES + "?fields=id", meta, headers=_auth(token))["id"]


def upload_as_sheet(token, name, xlsx_bytes, folder_id):
    """Multipart upload of an .xlsx, converted to a Google Sheet on arrival.
    Returns ``{id, name, webViewLink}``."""
    boundary = "adi_" + secrets.token_hex(8)
    meta = {"name": name, "mimeType": SHEET_MIME, "parents": [folder_id]}
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(meta)}\r\n"
        f"--{boundary}\r\nContent-Type: {XLSX_MIME}\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n"
    ).encode() + base64.b64encode(xlsx_bytes) + f"\r\n--{boundary}--\r\n".encode()
    url = DRIVE_UPLOAD + "?" + urllib.parse.urlencode({"uploadType": "multipart",
                                                       "fields": "id,name,webViewLink"})
    return _http("POST", url, body, headers=_auth(token),
                 content_type=f"multipart/related; boundary={boundary}")


def share_anyone_with_link(token, file_id, role="writer"):
    return _http("POST", f"{DRIVE_FILES}/{file_id}/permissions",
                 {"type": "anyone", "role": role}, headers=_auth(token))


def publish_rfq(refresh_token, show_code, filename, xlsx_bytes):
    """The whole export: token -> 01 - RFQs/<show> -> upload as Sheet ->
    anyone-with-link edit. Returns the Drive file dict (with webViewLink)."""
    token = access_token(refresh_token)
    root = find_or_create_folder(token, RFQ_FOLDER)
    sub = find_or_create_folder(token, show_code or "Show", parent_id=root)
    name = filename[:-5] if filename.lower().endswith(".xlsx") else filename
    created = upload_as_sheet(token, name, xlsx_bytes, sub)
    share_anyone_with_link(token, created["id"])
    return created
