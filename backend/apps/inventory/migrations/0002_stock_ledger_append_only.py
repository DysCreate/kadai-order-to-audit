"""Database-enforced append-only stock ledger.

The trigger rejects UPDATE and DELETE on ``inventory_stock_ledger`` at the
database level, not just in the application, so history cannot be rewritten by
a bug, an admin action or a shell script. Corrections must be reversing
entries, and benchmark resets use TRUNCATE (which does not fire row triggers)
explicitly through ``seed_benchmark --reset``.
"""

from django.db import migrations

CREATE_TRIGGER = """
CREATE OR REPLACE FUNCTION prevent_stock_ledger_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'stock_ledger is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER stock_ledger_append_only
BEFORE UPDATE OR DELETE ON inventory_stock_ledger
FOR EACH ROW EXECUTE FUNCTION prevent_stock_ledger_mutation();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS stock_ledger_append_only ON inventory_stock_ledger;
DROP FUNCTION IF EXISTS prevent_stock_ledger_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
