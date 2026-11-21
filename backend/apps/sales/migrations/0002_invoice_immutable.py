"""Database-enforced invoice immutability.

A posted invoice is a tax document: it can never be edited or deleted. The
trigger rejects UPDATE and DELETE on both the invoice header and its lines at
the database level, so a bug, an admin action or a shell script cannot rewrite
issued tax history. Corrections go through a credit note (``sales_credit_note``
plus its lines), and dispatch/credited quantities are derived from those
append-only documents rather than stored on the invoice.

Benchmark resets use TRUNCATE (which does not fire row triggers) explicitly
through ``seed_benchmark --reset``.
"""

from django.db import migrations

CREATE_TRIGGER = """
CREATE OR REPLACE FUNCTION prevent_invoice_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'posted invoices are immutable: % on % is not permitted', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER sales_invoice_immutable
BEFORE UPDATE OR DELETE ON sales_invoice
FOR EACH ROW EXECUTE FUNCTION prevent_invoice_mutation();

CREATE TRIGGER sales_invoice_line_immutable
BEFORE UPDATE OR DELETE ON sales_invoice_line
FOR EACH ROW EXECUTE FUNCTION prevent_invoice_mutation();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS sales_invoice_immutable ON sales_invoice;
DROP TRIGGER IF EXISTS sales_invoice_line_immutable ON sales_invoice_line;
DROP FUNCTION IF EXISTS prevent_invoice_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
