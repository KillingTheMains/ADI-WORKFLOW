"""`python3 migrations.py` must DO something, 2026-09-03.

Jason pasted a deploy block containing `python3 migrations.py` and reported
"nothing happened in the bash with that". He was right: the module had no
`__main__` block, so running it imported the file, defined some functions, and
exited. No migrations, no output, no error.

That is the worst possible shape for a deploy command — it is indistinguishable
from a successful no-op, and the house rule is "a migration reporting 0 when
you predicted otherwise is a FAILURE SIGNAL". A command that reports NOTHING
defeats that rule entirely.

It also explains an older mystery: migrations really run inside the app
(create_app → _run_db_startup → run_migrations), so on a normal boot their
output goes to the SERVER LOG, not a console. The five migration-bearing
deploys on 2026-08-12 "captured no console output" because there was never any
to capture.
"""
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    with open(os.path.join(_REPO, name)) as fh:
        return fh.read()


def test_migrations_can_be_run_directly():
    src = _src("migrations.py")
    assert '__name__ == "__main__"' in src, (
        "running migrations.py must do something; without this it imports and "
        "exits silently, which looks exactly like a successful deploy"
    )


def test_it_delegates_rather_than_reimplementing_startup():
    """A second copy of the startup sequence is how two doors start to drift —
    the same failure the headcount rule and the crew-placement helper both
    already produced in this codebase."""
    src = _src("migrations.py")
    tail = src[src.index('__name__ == "__main__"'):]
    assert "run_db_startup" in tail


def test_the_deploy_entry_point_still_exists():
    """migrations.py's __main__ depends on it, so a rename must break loudly
    here rather than at 6am on a show day."""
    assert "def run_db_startup" in _src("app.py")


def test_startup_forces_the_skip_flag_off():
    """The WSGI environment may set SKIP_DB_STARTUP=1 so boots do no DB work.
    A deploy-time run must ignore that or it does nothing, silently, again."""
    src = _src("app.py")
    fn = src[src.index("def run_db_startup"):]
    fn = fn[:fn.index("\ndef ")]
    assert "SKIP_DB_STARTUP" in fn and "pop" in fn
