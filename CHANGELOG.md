# Changelog

Entries are added under **Pending Deploy** as features land on `main`.
When the live site is updated (see [DEPLOY.md](./DEPLOY.md)), entries move
to **Deployed** with the date.

---

## Pending Deploy

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
