"""Add a PostgreSQL exclusion constraint that prevents overlapping bookings.

Why this migration exists separately
------------------------------------
SQLite (the development database) cannot express range-exclusion constraints.
The requirement "no overlap for the same car" is therefore enforced in two
layers:

1. **Application layer** — ``apps.bookings.services.assert_car_free()`` runs
   inside a transaction and locks the car row. This works on every backend.
2. **Database layer** — on PostgreSQL this migration adds an ``EXCLUDE USING
   gist`` constraint, which is the only way to make it a hard guarantee
   against concurrent writers.

The migration is a deliberate no-op on any non-PostgreSQL backend, so the same
migration graph applies to dev and production.
"""
from __future__ import annotations

from django.db import migrations

CREATE_CONSTRAINT = """
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE bookings_booking
    ADD CONSTRAINT booking_car_no_overlap
    EXCLUDE USING gist (
        car_id WITH =,
        daterange(start_date, end_date, '[]') WITH &&
    )
    WHERE (is_deleted = false AND status IN ('pending', 'confirmed', 'ongoing'));
"""

DROP_CONSTRAINT = """
ALTER TABLE bookings_booking DROP CONSTRAINT IF EXISTS booking_car_no_overlap;
"""


def create_constraint(apps, schema_editor) -> None:
    """Add the constraint on PostgreSQL; do nothing elsewhere."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(CREATE_CONSTRAINT)


def drop_constraint(apps, schema_editor) -> None:
    """Remove the constraint on PostgreSQL; do nothing elsewhere."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(DROP_CONSTRAINT)


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_constraint, drop_constraint),
    ]
