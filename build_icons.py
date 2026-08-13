"""Regenerate templates/_icons.html from the published Lucide package.

Interface Spec Rev 1 §05 says "copy each path from lucide.dev". The 21 glyphs
that were already here were drawn by hand and only resemble Lucide -- e.g.
`check` was "M4 12.5 9 17.5 20 6.5" where Lucide's is "M20 6 9 17l-5-5".
This script removes the possibility of that happening again: the paths come
out of lucide-static, pinned, and nothing is typed from memory.
"""
import re, os

ICONS = os.environ.get(
    'LUCIDE_ICONS',
    os.path.expanduser('~/.cache/adi-lucide/node_modules/lucide-static/icons'))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', '_icons.html')

SPEC = [
    ('layout-grid', 'Home'), ('undo-2', 'Recent Activity / Undo'),
    ('redo-2', 'Redo'), ('clipboard-list', 'Requests'), ('repeat', 'Recurring'),
    ('clapperboard', 'All Shows'), ('plus', 'New Show / add'), ('copy', 'Day Templates'),
    ('users', 'Crew Database'), ('user', 'a single person'), ('hard-hat', 'Local Labor'),
    ('clock', 'Times'), ('play', 'SOD'), ('flag', 'EOD'),
    ('cup-soda', 'Beverage'), ('coffee', 'Break'), ('utensils', 'Provided / F&B'),
    ('alert-triangle', 'Warning'), ('check', 'Saved'), ('palette', 'Agency Branding'),
    ('building-2', 'Vendors'), ('package', 'Equipment'), ('banknote', 'Budget'),
]
DEPT = [
    ('truck', 'Dock'), ('wind', 'Hazer'), ('lock', 'Doors'), ('shield', 'Security'),
    ('lightbulb', 'House LX'), ('snowflake', 'HVAC'), ('ticket', 'Wristbands'),
    ('headphones', 'COMS'), ('brush', 'Cleaning'),
]
SWEEP = [
    ('x', 'close / delete control'), ('save', 'save'), ('printer', 'print'),
    ('calendar', 'date'), ('plane', 'travel'), ('plane-takeoff', 'departure'),
    ('plane-landing', 'arrival'), ('map', 'map / venue'), ('download', 'export / download'),
    ('zap', 'power / quick action'), ('menu', 'list toggle'), ('paperclip', 'attachment'),
    ('radio', 'comms / radio'), ('file-text', 'document'), ('pencil', 'edit'),
    ('book-open', 'show book'), ('trash-2', 'delete'), ('search', 'search / empty state'),
    ('plug', 'power'), ('salad', 'catering item'), ('link', 'linked record'),
    ('mic', 'audio'), ('hotel', 'accommodation'), ('chart-column', 'report'),
    ('folders', 'grouping'), ('inbox', 'import'),
]


def inner(name):
    s = open(os.path.join(ICONS, name + '.svg'), encoding='utf-8').read()
    s = re.sub(r'(?s)<!--.*?-->', '', s)
    s = re.sub(r'(?s)^.*?<svg[^>]*>', '', s)
    s = s.replace('</svg>', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.replace(' />', '/>')


HEADER = '''{# ── Line icons ──────────────────────────────────────────────
   Interface Spec Rev 1 §05. Lucide (lucide.dev, ISC licence), stroke 1.5,
   16px default, stroke="currentColor" so an icon tracks its own link's hover
   and active state without a second rule.

   GENERATED -- do not hand-edit. Run build_icons.py against the pinned
   lucide-static package to regenerate. §05 says "copy each path from
   lucide.dev"; the 21 glyphs that used to live here were drawn from memory
   and only resembled Lucide (`check` was "M4 12.5 9 17.5 20 6.5" against
   Lucide's "M20 6 9 17l-5-5"). Generating removes that failure mode.

   Inlined rather than loaded: no sprite sheet, no icon font, no extra request,
   and -- the reason that actually matters here -- no dependence on a CDN on a
   laptop in a venue with bad wifi five minutes before a crew call.

   ⠿ IS NOT IN HERE, DELIBERATELY. The braille drag handle stays a character:
   it is a texture rather than a picture, it prints, and its hitbox is tuned in
   style.css with !important to beat the inline opacity. Do not "finish the
   job" by converting it.

   Usage:  {% import '_icons.html' as ico %}   then   {{ ico.icon('users') }}
#}

{% macro icon(name, size=16, cls='') -%}
<svg class="ico {{ cls }}" data-icon="{{ name }}"
     width="{{ size }}" height="{{ size }}" viewBox="0 0 24 24"
     fill="none" stroke="currentColor" stroke-width="1.5"
     stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true" focusable="false"
     style="flex-shrink:0;vertical-align:-.15em;">
'''

FOOTER = """{%- else -%}
{#- An unknown name draws nothing rather than a broken glyph. -#}
{%- endif -%}
</svg>
{%- endmacro %}
"""


def main():
    parts, first = [], True
    for group, label in ((SPEC, "§05's own table"),
                         (DEPT, 'SUB_SCHEDULE_META departments'),
                         (SWEEP, 'the template sweep')):
        parts.append('{#- ── %s ─ -#}' % label)
        for name, why in group:
            kw = 'if' if first else 'elif'
            first = False
            parts.append("{%%- %s name == '%s' -%%}{#- %s -#}" % (kw, name, why))
            parts.append(inner(name))
    body = HEADER + '\n'.join(parts) + '\n' + FOOTER
    open(OUT, 'w', encoding='utf-8').write(body)
    n = len(SPEC) + len(DEPT) + len(SWEEP)
    print('wrote %s' % OUT)
    print('glyphs: %d  bytes: %d' % (n, len(body)))


if __name__ == '__main__':
    main()
