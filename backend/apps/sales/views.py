"""Sales API views.

Thin: validate input, call a service, serialise the result. Role checks are
server-side and deny-by-default through ``RolePermission``; read and write
roles differ per endpoint, so ``initial`` selects the right set before the
permission check runs. A salesman's object scope is applied in the queryset,
so another salesman's order is a 404 rather than a leak.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, cast

from django.core import signing
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from core.permissions import RolePermission

from .models import Invoice, Order, OrderLine
from .pdf import (
    invoice_id_from_token,
    invoice_pdf_token,
    invoice_share_links,
    render_invoice_pdf,
)
from .serializers import (
    CreditNoteCreateSerializer,
    CreditNoteSerializer,
    CustomerSalesRowSerializer,
    DispatchCreateSerializer,
    DispatchSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    OrderCoverageSerializer,
    OrderCreateSerializer,
    OrderLineEditSerializer,
    OrderQuerySerializer,
    OrderRejectSerializer,
    OrderSerializer,
)
from .services import (
    CreditNoteLineInput,
    DispatchLineInput,
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
    customer_sales_summary,
    dispatch_invoice,
    edit_order_line,
    invoice_queryset_for,
    issue_credit_note,
    order_queryset_for,
    reject_order,
    stock_coverage,
)

READ_ROLES: tuple[str, ...] = (Role.SALESMAN, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER)
WRITE_ROLES: tuple[str, ...] = (Role.SALESMAN, Role.ADMIN, Role.OWNER)
ADMIN_ROLES: tuple[str, ...] = (Role.ADMIN, Role.OWNER)
ADMIN_READ_ROLES: tuple[str, ...] = (Role.ADMIN, Role.ACCOUNTANT, Role.OWNER)


class SalesAPIView(APIView):
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


class OrderCollectionView(SalesAPIView):
    """GET /api/sales/orders/ – inbox; POST – idempotent order submit."""

    def get(self, request: Request) -> Response:
        query = OrderQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        orders = order_queryset_for(_user(request))
        if "state" in query.validated_data:
            orders = orders.filter(state=query.validated_data["state"])
        if "customer" in query.validated_data:
            orders = orders.filter(customer_id=query.validated_data["customer"])
        return Response(OrderSerializer(orders, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = create_order(
            customer=serializer.validated_data["customer"],
            lines=[
                OrderLineInput(item_id=row["item"].pk, qty=row["qty"])
                for row in serializer.validated_data["lines"]
            ],
            client_uuid=serializer.validated_data["client_uuid"],
            salesman=_user(request),
            notes=serializer.validated_data.get("notes", ""),
        )
        status_code = 201 if submission.created else 200
        return Response(OrderSerializer(submission.order).data, status=status_code)


class OrderDetailView(SalesAPIView):
    """GET /api/sales/orders/<id>/ – one order, scoped to the salesman."""

    def get(self, request: Request, pk: int) -> Response:
        try:
            order = order_queryset_for(_user(request)).get(pk=pk)
        except Order.DoesNotExist as exc:
            raise Http404("Order not found.") from exc
        return Response(OrderSerializer(order).data)


class OrderSalesSummaryView(SalesAPIView):
    """GET /api/sales/orders/summary/?month=YYYY-MM – customer-wise sales."""

    def get(self, request: Request) -> Response:
        raw_month = request.query_params.get("month")
        month: date | None = None
        if raw_month not in (None, ""):
            try:
                year_text, month_text = raw_month.split("-", 1)
                month = date(int(year_text), int(month_text), 1)
            except (ValueError, TypeError):
                return Response({"detail": "month must be YYYY-MM."}, status=400)
        rows = customer_sales_summary(user=_user(request), month=month)
        return Response(CustomerSalesRowSerializer(rows, many=True).data)


class OrderCoverageView(SalesAPIView):
    """GET /api/sales/orders/<id>/coverage/ – stock coverage and GST preview."""

    read_roles = ADMIN_READ_ROLES

    def get(self, request: Request, pk: int) -> Response:
        order = get_object_or_404(Order, pk=pk)
        return Response(OrderCoverageSerializer(stock_coverage(order)).data)


class OrderApproveView(SalesAPIView):
    """POST /api/sales/orders/<id>/approve/ – admin verification."""

    read_roles = ADMIN_ROLES
    write_roles = ADMIN_ROLES

    def post(self, request: Request, pk: int) -> Response:
        order = approve_order(order=get_object_or_404(Order, pk=pk), user=_user(request))
        return Response(OrderSerializer(order).data)


class OrderRejectView(SalesAPIView):
    """POST /api/sales/orders/<id>/reject/ – reject with a reason."""

    read_roles = ADMIN_ROLES
    write_roles = ADMIN_ROLES

    def post(self, request: Request, pk: int) -> Response:
        serializer = OrderRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = reject_order(
            order=get_object_or_404(Order, pk=pk),
            reason=serializer.validated_data["reason"],
            user=_user(request),
        )
        return Response(OrderSerializer(order).data)


class OrderLineEditView(SalesAPIView):
    """PATCH /api/sales/orders/<id>/lines/<line_id>/ – audited quantity/price edit."""

    read_roles = ADMIN_ROLES
    write_roles = ADMIN_ROLES

    def patch(self, request: Request, pk: int, line_pk: int) -> Response:
        serializer = OrderLineEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = get_object_or_404(Order, pk=pk)
        line = get_object_or_404(OrderLine, pk=line_pk, order=order)
        edit_order_line(
            order=order,
            line=line,
            user=_user(request),
            qty=serializer.validated_data.get("qty"),
            unit_price=serializer.validated_data.get("unit_price"),
        )
        order.refresh_from_db()
        return Response(OrderSerializer(order).data)


class OrderInvoiceView(SalesAPIView):
    """POST /api/sales/orders/<id>/invoice/ – raise the GST invoice."""

    read_roles = ADMIN_ROLES
    write_roles = ADMIN_ROLES

    def post(self, request: Request, pk: int) -> Response:
        serializer = InvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = create_invoice(
            order=get_object_or_404(Order, pk=pk),
            user=_user(request),
            invoice_date=serializer.validated_data.get("invoice_date"),
        )
        return Response(InvoiceSerializer(invoice).data, status=201)


class InvoiceCollectionView(SalesAPIView):
    """GET /api/sales/invoices/ – invoices, scoped to the salesman."""

    def get(self, request: Request) -> Response:
        invoices = invoice_queryset_for(_user(request)).order_by("-created_at", "-pk")
        return Response(InvoiceSerializer(invoices, many=True).data)


class InvoiceDetailView(SalesAPIView):
    """GET /api/sales/invoices/<id>/ – one invoice with derived status."""

    def get(self, request: Request, pk: int) -> Response:
        try:
            invoice = invoice_queryset_for(_user(request)).get(pk=pk)
        except Invoice.DoesNotExist as exc:
            raise Http404("Invoice not found.") from exc
        return Response(InvoiceSerializer(invoice).data)


def _pdf_response(invoice: Invoice) -> HttpResponse:
    response = HttpResponse(render_invoice_pdf(invoice), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{invoice.number.replace("/", "-")}.pdf"'
    return response


class InvoicePdfView(SalesAPIView):
    """GET /api/sales/invoices/<id>/pdf/ – the invoice PDF for staff."""

    read_roles = ADMIN_READ_ROLES

    def get(self, request: Request, pk: int) -> HttpResponse:
        return _pdf_response(get_object_or_404(Invoice, pk=pk))


class InvoicePdfTokenView(APIView):
    """GET /api/sales/invoices/pdf/<token>/ – signed, expiring PDF for sharing.

    No session is required: the signed token carries the invoice id and an
    expiry, which is what makes a WhatsApp or email link usable by the customer
    without granting them the API.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request: Request, token: str) -> HttpResponse:
        try:
            invoice_id = invoice_id_from_token(token)
        except signing.BadSignature:
            return HttpResponse("This invoice link is invalid or has expired.", status=403)
        return _pdf_response(get_object_or_404(Invoice, pk=invoice_id))


class InvoiceDispatchView(SalesAPIView):
    """POST /api/sales/invoices/<id>/dispatch/ – post FG issues."""

    read_roles = ADMIN_ROLES
    write_roles = ADMIN_ROLES

    def post(self, request: Request, pk: int) -> Response:
        serializer = DispatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dispatch = dispatch_invoice(
            invoice=get_object_or_404(Invoice, pk=pk),
            lines=[
                DispatchLineInput(
                    invoice_line_id=row["invoice_line"],
                    qty=row["qty"],
                )
                for row in serializer.validated_data["lines"]
            ],
            user=_user(request),
            dispatch_date=serializer.validated_data.get("dispatch_date"),
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(DispatchSerializer(dispatch).data, status=201)


class InvoiceCreditNoteView(SalesAPIView):
    """POST /api/sales/invoices/<id>/credit-notes/ – cancel with a credit note."""

    read_roles = ADMIN_ROLES
    write_roles = ADMIN_ROLES

    def post(self, request: Request, pk: int) -> Response:
        serializer = CreditNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credit_note = issue_credit_note(
            invoice=get_object_or_404(Invoice, pk=pk),
            reason=serializer.validated_data["reason"],
            lines=[
                CreditNoteLineInput(
                    invoice_line_id=row["invoice_line"],
                    qty=row["qty"],
                )
                for row in serializer.validated_data["lines"]
            ],
            restock=serializer.validated_data.get("restock", False),
            user=_user(request),
            note_date=serializer.validated_data.get("note_date"),
        )
        return Response(CreditNoteSerializer(credit_note).data, status=201)


class InvoiceShareView(SalesAPIView):
    """GET /api/sales/invoices/<id>/share/ – WhatsApp and mailto links."""

    read_roles = ADMIN_ROLES
    write_roles = ADMIN_ROLES

    def get(self, request: Request, pk: int) -> Response:
        invoice = get_object_or_404(Invoice, pk=pk)
        token = invoice_pdf_token(invoice)
        pdf_url = request.build_absolute_uri(reverse("sales-invoice-pdf-token", args=[token]))
        return Response(invoice_share_links(invoice=invoice, pdf_url=pdf_url))
