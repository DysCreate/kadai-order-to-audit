"""Masters admin registration."""

from django.contrib import admin

from .models import Customer, Item, Supplier, UoM

admin.site.register(UoM)
admin.site.register(Item)
admin.site.register(Supplier)
admin.site.register(Customer)
