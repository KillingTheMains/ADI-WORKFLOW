---
target: day.html
total_score: 23
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
target_identity: "file:/home/claude/adi-workflow/templates/schedule/day.html"
target_fingerprint: "sha256:f85a1a7be7166c5c3a00ede98f74ad9ec9ad8a2e2fa3b36b1ef7a5ec13cc21c2"
target_path: /home/claude/adi-workflow/templates/schedule/day.html
timestamp: 2026-09-05T02-40-50Z
slug: templates-schedule-day-html
closed: true
---
Method: dual-agent (A: ac6cc1d0e88c340fe · B: ab291b2b1fe4622a9). Browser overlay skipped: live-server runs in the cloud workspace and the user's browser cannot reach it. Assessed day (/shows/5/schedule/21) has no sections, local labor, breaks or beverages — four of seven row kinds judged from source.

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of system status | 2 | Autosave "saved" 0.7rem fades in 1.2s; no dirty-row mark; hours badge reads legacy call_time/wrap_time |
| 2 | Match system / real world | 3 | Larry's vocabulary; mixed time formats (7:00 AM vs 07:00) |
| 3 | User control and freedom | 2 | Undo exists in audit trail but day page never points at it; delete = confirm() + full reload |
| 4 | Consistency and standards | 2 | Five delete affordances (218, 633, 827, 1172, 1268); gold in seven places vs "exactly two" |
| 5 | Error prevention | 3 | Date-rename guard (3393), duplicate-call-time warning (2140) |
| 6 | Recognition rather than recall | 2 | Eight two-letter chips, no legend; Stamp/Copy icon-only |
| 7 | Flexibility and efficiency | 3 | Autosave, drag, quick-add pills; no keyboard reorder/collapse |
| 8 | Aesthetic and minimalist | 2 | 668 inputs, 296 buttons; crew list rendered three times |
| 9 | Error recovery | 1 | Flash at page top while scroll-restore returns user mid-page |
| 10 | Help and documentation | 3 | Good copy, mostly hover-only |
| **Total** | | **23/40** | **Acceptable** |

## Design Specificity Verdict
Split: the timeline stream is product-specific (chips, anchor-as-rule, Larry's words); the crew table (90% of pixels) is generic Bootstrap admin. Detector: 42 findings, mostly false positives once style.css is resolved (hover ×10, cramped-padding ×3, all-caps ×3, side-tab, em-dash). Confirmed: #6c757d on #F4F1EA 4.16:1 in the header strip; #adb5bd group labels 2.07:1 / 1.97:1; catered pills 10.56px.

## Priority Issues
- [P1] Sticky crew-table header hides under the 56px top bar (style.css 526–529 th top:0 z-index:2 vs .top-bar z-index:50). Fix: top:56px via a --adi-topbar-h token. → harden
- [P1] Feedback/errors invisible at the moment of action: flash at top + scroll-restore mid-page; 1.2s autosave flash; no beforeunload. Fix: pinned aria-live flash region under top bar; persistent per-row saved state; beforeunload while save pending. → harden, clarify
- [P1] Crew-call and plain-activity headers are the same object (both #F4F1EA at 870–871; chip letters + 4px vs 2px rail only). Break vs beverage tints ~2 grey levels apart; activity vs local rails both 2px solid; all five tints within ~5 grey levels. Fix: crew-call header on Midnight/white like the PDF section header; silhouette not tint for break vs bev. → shape then polish (all five surfaces)
- [P1] Crew table reads as a form: 668 inputs, 97 always-visible red × beside 97 green checks; prints as boxes. Fix: border-transparent at rest, border on hover/focus-within (variable-value change only); reveal × on hover/focus; name the person in the confirm. → quieter
- [P2] Gold not rare: seven uses (71, 75, 52, 915, 1573, 1971, 2293, 251) vs guardrail. Fix: ink cyan for hints/counts. → quieter

## Persona Red Flags
- Alex: native <select> roster with no type-ahead (1586–1604); "+ Add crew row" below the last row; icon cluster unlabeled, no shortcuts.
- Sam: ⠿ handles are <span> (872, 1213); section collapse is <span onclick> (1152) no aria-expanded; crew inputs unlabeled; qty (1215) no title; no headings/list semantics on the timeline; "saved" not announced.
- Larry: tints vanish at low brightness; handles at .35 and break-delete × at .5 opacity disappear; "OSS" button assumes recall; ⚡ stamp tooltip-only; Recurring summary is developer shorthand; Apply Template warns against itself.

## Minor Observations
⏱/⏰ at day.html 407, 1745, 1894, 2521 escape test_no_emoji_in_templates.py (U+2300 block not scanned). sessionStorage scroll-restore contradicts the "no browser storage" line in PRODUCT.md — fix the doc line. Empty-state copy points to the sidebar for templates (moved). Off-token greys and hours-badge colours. "Bar" column header (1907). .act-drag-handle styled twice. Two shows named "Big". Day Call Sheet + Hours Summary triple page length.

## Questions to Consider
1. Read plate with one edit mode per call instead of 600 boxes? 2. Crew call as the only card, all other kinds single lines? 3. Why isn't the on-screen crew-call header the PDF's? 4. Fold the left column into the day header plate and give the timeline full width? 5. Seed a kitchen-sink day with all seven kinds for future critiques?
