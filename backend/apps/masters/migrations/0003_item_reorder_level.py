from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0002_item_standard_batch_hours_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="reorder_level",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.000"),
                help_text=(
                    "Raise a low-stock alert when on-hand stock falls below this "
                    "level. Zero means fall back to one batch's BOM requirement "
                    "(finished goods: only alert at zero)."
                ),
                max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
            ),
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                check=models.Q(("reorder_level__gte", 0)),
                name="chk_item_reorder_level_non_negative",
            ),
        ),
    ]
