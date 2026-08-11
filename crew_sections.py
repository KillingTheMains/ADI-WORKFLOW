"""Tiered crew-call sections (note 1, 2026-08-11).

Larry's real section headers nest. Production has 133 of them across 23
labels, and they fall into three shapes:

    ENCORE                      company, level 1
    ENCORE RIGGING              company + department, level 2 under ENCORE
    LEAD CREW                   neither — a manual section, level 1

So a section is a level-1 header, optionally holding level-2 sub-headers. A
level-1 header BOUND to a company (``company_id``) is what lets a newly added
person find their own section without being told; the label stays free text so
Larry can title it whatever he likes.

Nothing here renumbers or moves an existing header. Every row already in the
database is level 1 and unbound, which renders exactly as it does today.
"""


def _norm(s):
    return " ".join((s or "").split()).strip().lower()


def walk(rows):
    """Yield ``(row, level1_header, level2_header)`` for every crew row.

    ``rows`` must already be in display order. Header rows themselves are not
    yielded — this is about which section each PERSON sits in.
    """
    l1 = l2 = None
    for row in rows:
        if row.is_group_header:
            if (row.header_level or 1) <= 1:
                l1, l2 = row, None
            else:
                l2 = row
            continue
        yield row, l1, l2


def _matches_company(header, crew_member):
    """Does this level-1 header represent the person's company?

    Binding by ``company_id`` is authoritative. The label fallback is what
    makes the feature work on the headers already in production, which predate
    binding and only say "ENCORE".
    """
    if header is None or crew_member is None:
        return False
    if header.company_id and crew_member.company_id:
        return header.company_id == crew_member.company_id
    if crew_member.company is None:
        return False
    label = _norm(header.group_label)
    if not label:
        return False
    name = _norm(crew_member.company.name)
    code = _norm(crew_member.company.code)
    return label in (name, code) or (bool(code) and label == code)


def _matches_department(header, crew_member):
    """Does this level-2 header represent the person's department?

    Matched on the label's trailing words so "ENCORE RIGGING" matches a rigger
    whose position sits in the Rigging department — production labels repeat
    the company name in the sub-header.
    """
    if header is None or crew_member is None:
        return False
    dept = getattr(getattr(crew_member, "position", None), "department", None)
    if not dept:
        return False
    label = _norm(header.group_label)
    return bool(label) and _norm(dept) in label


def insert_index_for(rows, crew_member):
    """Where a new row for ``crew_member`` belongs in ``rows``.

    Returns an index into ``rows``. The old behaviour was "append", which is
    why new crew landed under whatever section happened to be last — the bug in
    note 3. Now the person's company picks the level-1 section and their
    position's department picks the sub-section, and they land at the end of
    the deepest section that matches.

    Falls back to the end of the list when nothing matches, which is both the
    old behaviour and the right answer for a show with no sections at all.
    """
    if crew_member is None:
        return len(rows)

    best_end = None      # end index of the best matching section so far
    best_score = 0
    cur_score = 0
    cur_end = None

    def close():
        nonlocal best_end, best_score
        if cur_score > best_score and cur_end is not None:
            best_score, best_end = cur_score, cur_end

    l1 = None
    for i, row in enumerate(rows):
        if row.is_group_header:
            level = row.header_level or 1
            if level <= 1:
                close()
                l1 = row
                cur_score = 2 if _matches_company(row, crew_member) else 0
                cur_end = i + 1 if cur_score else None
            else:
                # A sub-header only counts when we are inside the right company
                # (or inside no company section at all, e.g. a manual "LED CREW").
                close()
                in_company = (l1 is None) or _matches_company(l1, crew_member)
                if in_company and _matches_department(row, crew_member):
                    cur_score = 3
                    cur_end = i + 1
                else:
                    cur_score = 0
                    cur_end = None
            continue
        if cur_end is not None:
            cur_end = i + 1
    close()

    return best_end if best_end is not None else len(rows)


def renumber(rows):
    """Reassign sort_order in list order, leaving gaps for later inserts."""
    for i, row in enumerate(rows):
        row.sort_order = (i + 1) * 10
    return rows
