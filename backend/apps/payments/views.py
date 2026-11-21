"""Payments API views – thin, role-checked, deny-by-default.

The accountant is read-only: every write endpoint excludes the role. Payment
amounts and outstanding balances are serialised as strings (Decimals), never
floats.
"""

from __future__ import annotations

from typing import ClassVar, cast

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from apps.masters.models import Customer
from core.permissions import RolePermission

from .serializers import (
    AgeingBucketSerializer,
    CustomerLedgerSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
)
from .services import (
    PaymentAllocationInput,
    ageing_bucket_labels,
    customer_ageing,
    customer_ledger,
    customer_outstanding,
    payment_queryset_for,
    record_payment,
)

READ_ROLES: tuple[str, ...] = (Role.ADMIN, Role.ACCOUNTANT, Role.OWNER)
WRITE_ROLES: tuple[str, ...] = (Role.ADMIN, Role.OWNER)


class PaymentsAPIView(APIView):
    """Base view: reads and writes declare their own role sets."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: tuple[str, ...] = ()
    read_roles: ClassVar[tuple[str, ...]] = READ_ROLES
    write_roles: ClassVar[tuple[str, ...]] = WRITE_ROLES

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        safe = request.method in ("GET", "HEAD", "OPTIONS")
        self.allowed_roles = self.read_roles if safe else self.write_roles
        super().initial(request, *args, **kwargs)


def _user(request: Request) -> User:
    return cast(User, request.user)


def _customer_filter(request: Request) -> Customer | None:
    raw = request.query_params.get("customer")
    if raw in (None, ""):
        return None
    try:
        customer_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise Http404("customer must be a customer id.") from exc
    return get_object_or_404(Customer, pk=customer_id)


class PaymentCollectionView(PaymentsAPIView):
    """GET /api/payments/payments/ – list; POST – record and allocate."""

    def get(self, request: Request) -> Response:
        payments = payment_queryset_for(_user(request), customer=_customer_filter(request))
        return Response(PaymentSerializer(payments, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = record_payment(
            customer=serializer.validated_data["customer"],
            amount=serializer.validated_data["amount"],
            method=serializer.validated_data["method"],
            allocations=[
                PaymentAllocationInput(
                    invoice_id=row["invoice"].pk,
                    amount=row["amount"],
                )
                for row in serializer.validated_data["allocations"]
            ],
            payment_date=serializer.validated_data.get("payment_date"),
            reference=serializer.validated_data.get("reference", ""),
            notes=serializer.validated_data.get("notes", ""),
            user=_user(request),
        )
        return Response(PaymentSerializer(payment).data, status=201)


class CustomerOutstandingView(PaymentsAPIView):
    """GET /api/payments/outstanding/?customer=<id> – money still due."""

    def get(self, request: Request) -> Response:
        customer = _customer_filter(request)
        if customer is None:
            return Response(
                {"detail": "customer is required."},
                status=400,
            )
        return Response(
            {
                "customer_id": customer.pk,
                "customer_name": customer.name,
                "outstanding": str(customer_outstanding(customer)),
            }
        )


class CustomerAgeingView(PaymentsAPIView):
    """GET /api/payments/ageing/?customer=<id>&as_of=YYYY-MM-DD – ageing buckets."""

    def get(self, request: Request) -> Response:
        raw_as_of = request.query_params.get("as_of")
        as_of = None
        if raw_as_of not in (None, ""):
            as_of = parse_date(raw_as_of)
            if as_of is None:
                return Response({"detail": "as_of must be a date."}, status=400)

        customer = _customer_filter(request)
        if customer is not None:
            buckets = customer_ageing(customer, as_of=as_of)
            return Response(
                {
                    "customer_id": customer.pk,
                    "customer_name": customer.name,
                    "outstanding": str(customer_outstanding(customer)),
                    "buckets": AgeingBucketSerializer(buckets, many=True).data,
                }
            )

        rows = []
        for other in Customer.objects.order_by("name"):
            outstanding = customer_outstanding(other)
            if outstanding == 0:
                continue
            rows.append(
                {
                    "customer_id": other.pk,
                    "customer_name": other.name,
                    "outstanding": str(outstanding),
                    "buckets": AgeingBucketSerializer(
                        customer_ageing(other, as_of=as_of), many=True
                    ).data,
                }
            )
        return Response({"labels": ageing_bucket_labels(), "customers": rows})


class CustomerLedgerView(PaymentsAPIView):
    """GET /api/payments/customers/<id>/ledger/ – invoices, payments, ageing."""

    def get(self, request: Request, pk: int) -> Response:
        customer = get_object_or_404(Customer, pk=pk)
        ledger = customer_ledger(customer)
        return Response(CustomerLedgerSerializer(ledger).data)
