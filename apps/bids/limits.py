from contextlib import contextmanager
from threading import RLock
from weakref import WeakValueDictionary

from django.conf import settings
from django.db import connection
from django.db.models import F

from .models import Bid, BidCreationLock, BidRetentionPolicy, BidSystemSettings


ACTIVE_BID_STATUSES = (
    Bid.Status.UPLOADED,
    Bid.Status.PROCESSING,
    Bid.Status.READY,
    Bid.Status.FAILED,
)
_sqlite_user_locks = WeakValueDictionary()
_sqlite_user_locks_guard = RLock()


def get_default_bid_limit():
    """Return the configured site default, falling back safely before migration."""
    settings_row = BidSystemSettings.objects.filter(pk=1).only("default_bid_limit").first()
    return settings_row.default_bid_limit if settings_row else getattr(settings, "DEFAULT_ACTIVE_BID_LIMIT", 1)


def get_effective_bid_limit(user):
    override = BidRetentionPolicy.objects.filter(user_id=user.pk).values_list("bid_limit", flat=True).first()
    return override if override is not None else get_default_bid_limit()


def get_active_bid_count(user):
    return Bid.objects.filter(uploaded_by_id=user.pk, status__in=ACTIVE_BID_STATUSES).count()


def lock_user_bid_slots(user):
    """Acquire the per-user creation lock; caller must be inside atomic()."""
    if connection.vendor == "sqlite":
        # The row is seeded for all existing accounts and created by the user
        # post_save signal. Make this the transaction's first SQL statement so
        # SQLite reserves its writer before another request reads the count.
        updated = BidCreationLock.objects.filter(user_id=user.pk).update(
            lock_version=F("lock_version") + 1
        )
        if updated:
            return
        BidCreationLock.objects.create(user_id=user.pk)
        return
    lock, _created = BidCreationLock.objects.get_or_create(user_id=user.pk)
    BidCreationLock.objects.select_for_update().get(pk=lock.pk)
    BidCreationLock.objects.filter(pk=lock.pk).update(lock_version=F("lock_version") + 1)


@contextmanager
def user_bid_creation_guard(user):
    """Serialize SQLite threads; database row locking handles other backends."""
    if connection.vendor != "sqlite":
        yield
        return
    key = (connection.alias, user.pk)
    with _sqlite_user_locks_guard:
        lock = _sqlite_user_locks.setdefault(key, RLock())
    with lock:
        yield


def bid_limit_message(limit):
    return f"You have reached your maximum active bid limit of {limit}. Please complete or delete an existing bid before creating another bid."
