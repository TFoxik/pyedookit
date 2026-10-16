from decimal import Decimal
from pathlib import Path

import pytest

from pyedookit.exceptions import ParseError
from pyedookit.models import PaymentRequest
from pyedookit.parsers.payments import parse_amount, parse_payments

FIXTURE = (Path(__file__).parent / "fixtures" / "payments_structure.html").read_text()


def test_summary_uses_everyone_totals():
    payments = parse_payments(FIXTURE)
    assert (payments.paid, payments.remaining, payments.overpaid) == (
        Decimal(1234),
        Decimal(321),
        Decimal(0),
    )
    assert payments.currency == "CZK"


def test_requests_and_paid_status():
    assert parse_payments(FIXTURE).requests == [
        PaymentRequest("Testovací poplatek A", Decimal(1234), "CZK", is_paid=True),
        PaymentRequest("Testovací poplatek B", Decimal(321), "CZK", is_paid=False),
    ]


def test_parse_amount_handles_czech_formats():
    assert parse_amount("0 Kč") == (Decimal(0), "CZK")
    assert parse_amount("1 400 Kč") == (Decimal(1400), "CZK")
    assert parse_amount("1 400,50 Kč") == (Decimal("1400.50"), "CZK")
    assert parse_amount("12 €") == (Decimal(12), "EUR")
    assert parse_amount("250") == (Decimal(250), None)


def test_parse_amount_rejects_text_without_a_number():
    with pytest.raises(ParseError):
        parse_amount("zdarma")


def test_missing_summary_raises():
    with pytest.raises(ParseError):
        parse_payments('<section class="content"><h1>Platby</h1></section>')
