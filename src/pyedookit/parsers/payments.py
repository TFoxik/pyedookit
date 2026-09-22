from __future__ import annotations

import logging
import re
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from ..exceptions import ParseError
from ..models import PaymentRequest, Payments

_AMOUNT_RE = re.compile(r"(-?\d[\d\s ]*(?:,\d+)?)\s*(\S+)?")
_CURRENCIES = {"Kč": "CZK", "CZK": "CZK", "€": "EUR", "EUR": "EUR"}
_DEFAULT_CURRENCY = "CZK"

_LOGGER = logging.getLogger(__name__)


def parse_amount(text: str) -> tuple[Decimal, str | None]:
    match = _AMOUNT_RE.search(text)
    if match is None:
        raise ParseError(f"no amount in {text!r}")
    number = re.sub(r"[\s ]", "", match.group(1)).replace(",", ".")
    return Decimal(number), _CURRENCIES.get(match.group(2) or "")


def parse_payments(html: str) -> Payments:
    """Parse `/payments/` ("Platby") for the whole family.

    Totals come from the `Everyone` spans because the portal bills parents
    as well as the child. Only paid requests (`div.accepted`) have been seen
    on a real portal, so every other request counts as unpaid and the
    summary's "remaining" total stays the authoritative number.
    """
    soup = BeautifulSoup(html, "lxml")
    summary = soup.select_one("table.payments-summary.desktop") or soup.select_one(
        "table.payments-summary"
    )
    if summary is None:
        raise ParseError("no payments summary table found")

    paid, currency = _total(summary, "td.paid span.sumsEveryone")
    remaining, _ = _total(summary, "td.remaining span.sumsEveryone")
    overpaid, _ = _total(summary, "td.overpaymentEveryone span")

    requests: list[PaymentRequest] = []
    for item in soup.select("div.item.prescriptionEveryone"):
        request = _parse_request(item, currency)
        if request is None:
            _LOGGER.warning("skipping unparseable payment request")
        else:
            requests.append(request)
    return Payments(
        paid=paid, remaining=remaining, overpaid=overpaid, currency=currency, requests=requests
    )


def _total(summary: Tag, selector: str) -> tuple[Decimal, str]:
    cell = summary.select_one(selector)
    if cell is None:
        raise ParseError(f"payments summary has no {selector}")
    amount, currency = parse_amount(cell.get_text(" ", strip=True))
    return amount, currency or _DEFAULT_CURRENCY


def _parse_request(item: Tag, default_currency: str) -> PaymentRequest | None:
    title = item.select_one("div.heading div.text")
    amount_cell = item.select_one("div.column.c4.desktop div.amount") or item.select_one(
        "div.amount"
    )
    if title is None or amount_cell is None:
        return None
    try:
        amount, currency = parse_amount(amount_cell.get_text(" ", strip=True))
    except ParseError:
        return None
    return PaymentRequest(
        title=title.get_text(" ", strip=True),
        amount=amount,
        currency=currency or default_currency,
        is_paid=item.select_one("div.status-icon div.accepted") is not None,
    )
