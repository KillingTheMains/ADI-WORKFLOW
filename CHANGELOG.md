# Changelog

Entries are added under **Pending Deploy** as features land on `main`.
When the live site is updated (see [DEPLOY.md](./DEPLOY.md)), entries move
to **Deployed** with the date.

---

## Pending Deploy

### Day editor: inline edit for crew rows within an activity
- The crew table under each activity is now inline-editable per row.
- Editable fields: Qty, Hours, Position (with autocomplete from the
  master Position list — but free text also accepted), Name (as a
  display override), and Crew Type (Lead / Local / Vendor / Union).
- Save button (💾) per row. Delete (✕) still there. Free-text position
  that matches an existing master Position now auto-sets position_id
  so hours reports pick it up.

### Show Crew Booking Sheet: drag-to-reorder within each task card
- The same drag-and-drop reorder from the master roster is now on
  every show's Booking Sheet page. Each Booking Task card (PREP /
  Set Up / 3 Show / Strike) is a separate sortable — grab any row
  by the ⋮⋮ handle on the left, drop it where you want.
- Real crew assignments and TBD slots share the same order within a
  card so you can freely arrange them together.
- The "Fill this slot →" row that appears below each TBD stays
  attached to its parent slot even after drag — JS reattaches it
  automatically on drop.
- New `sort_order` column on both `show_crew_assignments` and
  `show_open_slots` (auto-migration).

### Crew Roster: inline edit + drag-to-reorder
- Every crew row on the master roster is now inline-editable — First
  name, Last name, Position (dropdown), Company (dropdown), Email,
  Phone. Edit and hit the 💾 Save button per row.
- **Rows are draggable** by the ⋮⋮ handle on the left. Grab and drag
  a row up or down; the new order saves automatically on drop.
  Works on touch too. Powered by SortableJS (CDN).
- Rates, active/inactive, and notes still live behind the "…more"
  link (full edit form).
- New `sort_order` column on `crew_members` (auto-migration).
  Auto-backfilled with alphabetical order on first view so existing
  rosters land in the same order they were.

### Wishlist quick-fix batch
- **Activity times now display 12-hour with AM/PM** everywhere — day
  editor headers, schedule overview, OSS master view. Underlying
  storage stays HH:MM 24hr (what `<input type="time">` submits), just
  the display converts. New `to_12hr` Jinja filter.
- **New activities auto-sort by time.** Adding a 5:30 AM activity to
  a day that already has one at 8:00 AM now lands above it, not at
  the bottom of the list. Editing an activity's time also re-sorts;
  editing only the description leaves the order alone.
- **OSS Master Schedule now includes F&B** (meal services + their
  locations) alongside the other departments. Interleaved with
  Dock/Doors/etc. by time, day-by-day. Fixes the "Daily OSS doesn't
  populate the main overall schedule" report — F&B had disappeared
  from that view after the Phase C migration.

### Phase C — F&B v2 (multi-location meal services)
- OSS F&B tab rebuilt as a structured meal planner.
- Three new models: `MealService` (per meal event on a show day, with
  an optional link to a schedule activity), `MealServiceLocation`
  (1..N per service — Backstage, FOH, Local Labor, etc.), and
  `ShowDietaryNote` (per-show dietary preference rollup).
- Tab UI groups services by day. Each service is a card with an
  inline-editable table of locations (name, start, end, headcount,
  notes). Total headcount rolls up automatically at the top of the
  card. "+ Add location" per service; "+ Add meal service" per day.
- Dietary preferences section at the bottom of the tab — inline
  editable table with preference / % / count / notes.
- **Data migration:** existing `type='F&B'` SubScheduleEntry rows were
  auto-converted into one MealService + one MealServiceLocation each,
  preserving activity_id, time (from linked activity when present),
  count, and notes. Old F&B rows deleted. Registered in
  DATA_MIGRATIONS as `2026-06-30-fb-v2-migrate-entries`; will run
  once per environment on next reload.
- Meal-break detection now uses `MealService.activity_id` instead of
  the old F&B entry. All existing warnings still work.

### Phase B — Per-crew Travel detail (hotel + flights)
- New **✈ Travel** page on each show (linked from the Crew page top
  actions). One row per assigned crew member with inline-editable
  hotel + flight detail.
- Hotel columns: name, check-in, check-out, nights (auto from dates),
  confirmation #, cost. Show-wide grand-total hotel cost in the header.
- Flight columns: arrival flight # + time, departure flight # + time,
  itinerary link.
- 10 new nullable columns on `show_crew_assignments` (auto-migration).
- Importer extended to read File 2-style sheets:
  * Aliases for Check-in / Check-out / Confirmation / Total Hotel Cost.
  * Recognizes combined "SW WN2877 / 5:35pm" cells and splits them
    into flight + time fields automatically.
  * Travel info applies to the show assignment when uploading with
    target_show_id set.
- The same edit endpoint now serves both the Booking Sheet and the
  Travel page — each form posts only the fields it owns, so they
  don't blank each other's data.

### Phase A — Enriched crew booking sheet (per show)
- The Show Crew page gains a **📋 Booking Sheet** at the top — one
  table per Booking Task (PREP / Set Up / 3 Show / Strike / etc.),
  each row inline-editable.
- ShowCrewAssignment now stores per-show booking info per person:
  `booking_task`, `travel_in_date`, `start_date`, `end_date`,
  `travel_out_date`.
- **TBD / Open Slots** are first-class: click `+ Add TBD slot` to add
  unfilled positions (LOCAL LABOR pattern). Each TBD row carries the
  same booking-info shape and can later be filled — converting it to a
  real assignment carries the dates and task across.
- New `show_open_slots` table for TBD rows. Five new columns added to
  `show_crew_assignments` (auto-migration).

### Bulk importer extended for File-1 style sheets
- Crew import accepts new columns: **Booking Task, Travel In, Start,
  End, Travel Out** (with flexible header naming).
- New "📥 Import Crew to this Show" button on the Show Crew page —
  uploads target the current show. When set, the importer also
  creates/updates the per-show booking info on the assignment.
- Rows with first name "TBD" (or blank) plus a Position become
  ShowOpenSlot rows on the target show, not crew members on the
  master roster.
- Importer can still target the master roster only (no show selected)
  for general crew adds.

### Bulk crew import from XLSX
- New 📥 Import Crew button at the top of the Crew Roster page.
- Upload an .xlsx with crew info → preview page → review per-row → apply.
- Smart matching: by email first, falls back to first+last+company.
- "Fill blanks only" by default — never overwrites existing values
  unless you tick the per-field overwrite checkbox in the preview's
  Conflict box.
- Per-row decision dropdown: Add new / Update (fill blanks) / Skip.
- Unknown Position or Company? Preview shows a per-row picker:
  Create new / Map to existing / Leave blank. Nothing is created until
  you click Apply — cancelling leaves master lists untouched.
- New `crew_import_sessions` table (auto-created) holds the parsed
  rows + per-row decisions between upload and commit.
- Requires `openpyxl==3.1.5` — added to requirements.txt. **PA deploy
  needs `pip install openpyxl==3.1.5 --user` in the PA Bash console
  once before the reload.**
- PDF support deferred to v2 once we see the actual PDF format.

### Wristbands tab — rebuilt as a derived day-by-day count
- No more "add entry" form. The Wristbands tab is now a single editable
  table with one row per scheduled day.
- **Crew on day** is auto-derived from the schedule: unique named crew
  + sum of unnamed qty across every activity on that day.
- **Override** input lets you replace the auto count when the schedule's
  headcount isn't quite right.
- **Extras** input adds on top (VIPs, talent, sponsor walkthroughs).
- **Total** = (Override or Auto) + Extras, with a show-wide grand total
  in the footer.
- Per-day **Notes** field saved alongside the counts.
- Schema: schedule_days gets wristband_crew_override / wristband_extras /
  wristband_notes columns (auto-migration).

### COMS beltpack channels are now fixed K1–K6 slot dropdowns
- Replaced the click-order checkbox grid with N labeled slot dropdowns
  (K1, K2, K3…) per crew member.
- Each slot is an independent dropdown of the show's beltpack channels.
- **Slot count is brand-aware**: Riedel = 6, ClearCom = 4, Telex = 2,
  HME = 4, Other / unset = 6. Switching brand hides slots that don't
  exist on that pack and clears their stored value.
- **Gaps are preserved**: assigning K1=Main, K2=(blank), K3=LX is a
  real production pattern and now stores and reloads correctly.
  Storage uses an ordered CSV with empty entries for gaps (`5,,7`).
  Trailing empties are auto-trimmed on save.
- Hard 6-channel cap stays as the server-side safety net.
- Model: CrewCommAssignment.channel_id_list getter/setter handle
  None entries for gaps; new filled_channel_count helper.

### Fix: COMS pack fields no longer locked behind the 🎧 checkbox
- Wired/Wireless, Brand, and channel checkboxes were starting `disabled`
  until the headset checkbox was ticked, which made them feel broken.
- Now they're always interactive. Touching any of them auto-ticks 🎧
  for you so the pack assignment commits on save.
- Help text under the table updated to reflect this.

### COMS tab — radios + beltpacks are now separate
- The top of the COMS tab is a **split panel**:
  * Left: **📻 Radio channels (1–16)** — every show gets 16 named slots,
    auto-created on first view. Two-column grid for compact layout.
    Batch save with one button.
  * Right: **🎧 Beltpack channels** — the flexible per-show list
    (Main, LX, Cam, etc.) lives in this column.
- Crew gear assignment table now uses an **ordered checkbox grid** for
  beltpack channel selection instead of a plain multi-select. Click order
  IS the key order on the physical pack — first click = key 1, etc. Each
  selected channel shows a gold position badge `[1] [2] [3]`.
- **Hard cap of 6 channels per pack** (Riedel Bolero standard). Trying to
  pick a 7th shows an alert and blocks the click. Server-side cap mirrors
  the client cap defensively.
- **Brand-aware soft warning:** a yellow note appears next to the counter
  when you exceed the brand's typical channel count
  (ClearCom 4, Telex 2, HME 4) but stay under the hard 6.
- Schema: new `radio_channels` table (auto-created).

### COMS tab — rebuilt as a per-crew gear assignment table
- No more "add entry" form. The COMS tab now manages two things:
  1. **Show channel list** — define the channels this show uses
     (Main, LX, Cam, etc.) once. Add/remove with one click. Removing a
     channel automatically clears it from any crew assignment that
     referenced it.
  2. **Crew assignment table** — one row per crew assigned to the show
     (auto-created on first view), with checkboxes for 📻 Radio and
     🎧 Headset, dropdowns for Wired/Wireless and Brand (Riedel /
     ClearCom / Telex / HME / Other), a multi-select of channels (only
     enabled when Headset is checked), and Notes.
- Summary header counts radios, wireless packs, wired packs, and any
  crew not yet assigned comms.
- Schema: two new tables — show_comm_channels and crew_comm_assignments
  (auto-created by db.create_all()).

### Meal-break F&B detection (Piece 2)
- The app now recognizes activities containing LUNCH, DINNER, BREAKFAST,
  or MEAL as meal breaks.
- Schedule day editor: meal-break activities without a linked F&B entry
  get a small ⚠ no F&B badge next to the activity name.
- OSS hub F&B tab: the tab heading shows a ⚠ N badge counting missing
  F&B across the whole show. The tab body shows a list of the specific
  meal breaks that need attention, each linking to that day's editor.

### Graceful activity deletion (Piece 3)
- Deleting a schedule activity no longer leaves orphaned OSS entries.
- Linked OSS entries get their activity_id set to NULL and inherit the
  activity's last-known time, so they survive as unlinked operational
  items on the day rather than disappearing.
- A flash message tells you how many OSS entries got unlinked.

### Cross-view awareness (Piece 4)
- Schedule overview now shows a 🗺 N OSS badge on each day card that has
  OSS entries, linking to the OSS hub.

### Schedule and OSS are now one unified day view (Piece 1 of unification)
- Schedule day editor now shows OSS items inline:
  * Each activity card has an "OSS · linked to this activity" strip
    underneath the crew table. Linked items show as compact pills with
    their department icon, label, count, and a delete button.
  * Per-activity **+ OSS** button reveals a collapsible inline form
    that creates an OSS entry pre-linked to that activity. Time
    auto-pulls from the activity.
  * A new card at the bottom of the day, **📌 Operational items**, lists
    OSS entries that aren't tied to an activity (dock arrivals, etc.)
    with a sortable table and an inline add row.
  * When a day has no unlinked OSS yet, a small expandable form appears
    so you can drop one in without leaving the day editor.
- OSS CRUD routes now respect a `next=` field so add/edit/delete from
  the day editor stays on the day editor.

### OSS entries can link to schedule activities
- Each OSS entry now optionally links to a specific activity on the day
  it belongs to (e.g. an F&B "Crew lunch" entry can link to the
  "LUNCH BREAK" activity on the schedule).
- When linked, the entry's displayed time follows the activity's time —
  no more double-bookkeeping when the schedule shifts.
- When not linked, freeform time still works (good for Dock arrivals
  and other operational items that don't map to show activities).
- UI: linked entries show a 🔗 next to the time. The add/edit forms have
  a per-day activity dropdown; selecting an activity locks the time
  field to the activity's value.
- Schema: added nullable `activity_id` FK to `sub_schedule_entries`
  (auto-migration handles it).

### Sidebar navigation tweaks
- Show list now appears under **All Shows** (links to show detail).
- New **Schedule Builder** section above Databases, with per-show links
  going straight to the schedule overview, plus Day Templates moved
  here from Databases.
- Crew Roster keeps its existing per-show sub-list (each goes to that
  show's crew page).
- Extracted the repeated show-link markup into a single Jinja macro.

### OSS (On-Site Schedule) — first version
- New OSS hub at `/shows/<id>/oss` with tabs:
  Master Schedule, Dock, Haze, Doors, Security, F&B, House LX, HVAC,
  Wristbands, COMS, Cleaning, and the Show Book printable.
- Each tab supports add / edit / delete of entries, anchored to a
  scheduled day.
- Show detail page's "Coming soon" cards (Dock, F&B, COMMS, Wristbands)
  now link into OSS tabs. Added OSS Hub and Show Book quick links.
- The old `/shows/<id>/schedule/oss` URL is retired; the printable is
  now at `/shows/<id>/oss/show-book`. Buttons in the schedule overview
  and day editor were updated to match.

### Auto-migration system
- New `migrations.py` reconciles the live SQLite schema with the model
  on app startup. Idempotent — adds missing columns, skips existing.
- Removes the need to run `ALTER TABLE` by hand on PA after deploys.

### Schema changes (auto-applied on first reload after deploy)
- `sub_schedule_entries.schedule_day_id INTEGER REFERENCES schedule_days(id)`
- `sub_schedule_entries.count INTEGER`

---

## Deployed

_(No deploys logged yet. The OSS work above will be the first entry here
after the next push to PA.)_
