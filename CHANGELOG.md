# Changelog

Entries are added under **Pending Deploy** as features land on `main`.
When the live site is updated (see [DEPLOY.md](./DEPLOY.md)), entries move
to **Deployed** with the date.

---

## Pending Deploy

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
