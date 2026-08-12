"""Qt object-lifecycle helpers for breaking Python↔C++ reference cycles.

Long-lived child widgets must not keep a strong Python reference back to an
ancestor (MainWindow, BatchSheet, …) via a stored bound method or a
``.connect(lambda …)`` closure.  PyQt's normal signal/slot wiring already ties
slot lifetime to the *receiver* QObject; the helpers here cover the other
shape — a plain attribute that holds a callable for the widget's whole life
(pull-based providers, disk-path handlers, replot hooks).

``weak_bound`` is the shared form of the BatchSheet-local helper that stopped
the zombie-wrapper teardown cluster: the returned closure never names ``self``
directly, so it cannot keep the owner alive past its own refcount.
"""
from __future__ import annotations

import weakref
from typing import Any, Callable, Optional

__all__ = (
    "weak_bound",
    "as_weak_callable",
    "resolve_weak_callable",
    "call_weak_callable",
)


def weak_bound(bound_method: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a bound method in a closure that only holds it weakly.

    Used for callbacks handed to a descendant widget to keep as a plain
    attribute for the owner's whole lifetime (as opposed to a normal Qt
    signal/slot connection, which PyQt already ties to the receiver's
    lifetime). Without this, the descendant is a strong Python reference
    back to ``self`` that outlives ``self``'s own underlying C++ object
    whenever the owner's Qt parent is torn down by ordinary refcounting
    rather than an explicit ``close()`` — pytest-qt's parentless test hosts
    do exactly that. The closure below never touches ``self`` directly, so
    it does not keep it alive; if the owner is already gone, the call is
    silently skipped (returns ``None``).
    """
    ref = weakref.WeakMethod(bound_method)

    def _call(*args, **kwargs):
        method = ref()
        if method is not None:
            return method(*args, **kwargs)
        return None

    return _call


def as_weak_callable(
    fn: Optional[Callable[..., Any]],
) -> Optional[Callable[..., Any]]:
    """Store ``fn`` without keeping a bound-method owner alive.

    * Bound methods → ``weak_bound`` wrapper.
    * ``None`` → ``None``.
    * Plain functions / already-weak wrappers → returned as-is.
    """
    if fn is None:
        return None
    # Bound method: has __self__ and __func__. Free functions and nested
    # closures do not; leaving them alone is intentional — callers that
    # must break a cycle should pass a bound method (or call weak_bound
    # themselves) rather than a self-capturing lambda.
    if getattr(fn, "__self__", None) is not None and getattr(fn, "__func__", None) is not None:
        try:
            return weak_bound(fn)
        except TypeError:
            # Some extension types refuse WeakMethod; fall through.
            return fn
    return fn


def resolve_weak_callable(
    stored: Optional[Callable[..., Any]],
) -> Optional[Callable[..., Any]]:
    """Resolve a value produced by ``as_weak_callable`` / ``WeakMethod``.

    ``weak_bound`` already returns a live callable (that no-ops when dead),
    so most call sites can invoke ``stored`` directly. This helper exists
    for call sites that store a raw ``weakref.WeakMethod``.
    """
    if stored is None:
        return None
    if isinstance(stored, weakref.WeakMethod):
        return stored()
    return stored


def call_weak_callable(
    stored: Optional[Callable[..., Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Invoke a weakly-held callable; return ``None`` when the owner is gone."""
    fn = resolve_weak_callable(stored)
    if fn is None:
        return None
    return fn(*args, **kwargs)
