"""Repo-root pytest configuration.

This file exists for exactly one reason: to repair an upstream pytest
regression that silently drops a directory ``conftest.py``'s fixtures. Do not
put project fixtures here — directory conftests own those.

The bug (observed on pytest 9.1.1)
----------------------------------
``Session.collect`` walks each command-line argument from the rootdir down,
reusing already-built collector nodes through ``Session._collection_cache``.
That cache is bypassed — and overwritten — for an argument that names a file
directly::

    # _pytest/main.py, Session.collect
    handle_dupes = not (
        len(matchparts) == 1
        and isinstance(matchparts[0], Path)
        and matchparts[0].is_file()
    )
    rep, duplicate = self._collect_one_node(matchnode, handle_dupes)

The intent is backward compat for ``pytest test_a.py test_a.py``, but the
node being re-collected is the argument's **parent directory**, so the
re-collection throws away every child node that directory produced earlier
and builds fresh ones. With an argument list that leaves and re-enters a
directory::

    pytest tests/ui/test_a.py tests/test_root.py tests/ui/test_b.py

the middle argument re-collects ``Dir('tests')``, which mints a *second*
``Package('tests/ui')`` node object; the third argument then reads that one
out of the refreshed cache.

Everything ``tests/ui/conftest.py`` owns is bound to the **first** node
object, and pytest 9 keys both halves of fixture lookup by node identity
(``Node`` has no ``__eq__``):

* autouse names — ``FixtureManager._node_autousenames[<Directory node>]``,
  filled once per directory from ``_pending_conftests``, which is ``pop``-ed;
* fixture visibility — ``FixtureManager._matchfactories`` accepts a
  ``FixtureDef`` when ``fixturedef.node in node.iter_parents()``.

So tests collected under the duplicate node lose the directory's fixtures
entirely. Nothing warns: they just run without them. Here that silently
disabled ``tests/ui/conftest.py``'s ``_isolate_qsettings`` and
``_isolate_app_style``, so ``tests/ui/test_inspector.py`` read the
developer's **real** ``MF4Analyzer/DataAnalyzer`` preference store and
inherited a leaked application stylesheet — order-dependent failures whose
tracebacks point at the assertions, never at the missing fixtures.

The repair
----------
Restore the invariant the rest of pytest assumes: one directory, one node.
When a directory collector is collected more than once in a session, hand
back the child nodes it produced the first time instead of the fresh
duplicates. The re-collected directory node is itself the same object, so
the reused children keep a correct ``parent`` chain, and their own cached
collect reports (also keyed by node) stay reachable.

This is deliberately narrow. Only **sub-directory** children are reused —
file collectors are left to be rebuilt exactly as pytest rebuilds them
today, so the backward-compat behaviour that branch exists for (naming the
same file twice on the command line runs it twice) is untouched. It becomes
a no-op the moment pytest stops re-collecting directories, so it degrades
quietly on other versions. ``tests/test_conftest_autouse_scope.py`` is the
guard that fails if the underlying problem comes back — delete both once the
minimum supported pytest keeps directory conftests attached across
re-entering arguments.
"""

import pytest


_CHILD_CACHE_ATTR = "_mf4_directory_child_nodes"

# ``pytest.Directory`` is the base of ``Dir``/``Package``; on a pytest that
# predates it, no directory node can be duplicated and the shim stays idle.
_DIRECTORY = getattr(pytest, "Directory", ())


def _reuse_directory_children(collector, report):
    """Give a re-collected directory back the sub-directory nodes it made before."""
    result = getattr(report, "result", None)
    if not report.passed or not result:
        return
    if not isinstance(collector, _DIRECTORY):
        return  # Only directory collectors get re-collected this way.

    seen = getattr(collector.session, _CHILD_CACHE_ATTR, None)
    if seen is None:
        seen = {}
        setattr(collector.session, _CHILD_CACHE_ATTR, seen)
    # Keyed by node id, not object identity: the directory being re-collected
    # is the same object, and a node id names one collection position.
    known = seen.setdefault(collector.nodeid, {})

    reused = []
    for child in result:
        if not isinstance(child, _DIRECTORY):
            reused.append(child)
            continue
        reused.append(known.setdefault((type(child), child.path), child))
    report.result = reused


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    report = yield
    _reuse_directory_children(collector, report)
    return report
