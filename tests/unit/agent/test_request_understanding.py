"""Unit tests for deterministic natural-language request understanding."""

from decimal import Decimal

import pytest

from agent.request_understanding import (
    RequestUnderstanding,
    UnsupportedRequestError,
    parse_request,
)
from agent.runtime.service import AgentRequest


@pytest.mark.parametrize(
    "text",
    [
        "Buy ₦5,000 MTN airtime for 08030000001.",
        "Buy 5000 MTN airtime for 08030000001",
        "Purchase ₦5000 MTN airtime for 08030000001",
        "Please buy ₦5,000 MTN airtime for 08030000001.",
        "buy ₦5000 mtn airtime for 08030000001",
        "Can you get ₦5,000 MTN airtime sent to 08030000001?",
        "Buy NGN 5000 MTN airtime for 08030000001",
        "Buy ₦5,000.00 MTN airtime for 08030000001",
    ],
)
def test_supported_forms_parse_to_canonical_agent_request(text: str) -> None:
    request = parse_request(text)

    assert isinstance(request, AgentRequest)
    assert request.intent == "airtime_purchase"
    assert request.service_type == "airtime"
    assert request.product_type == "airtime"
    assert request.network == "MTN"
    assert request.beneficiary == "08030000001"
    assert request.amount == Decimal("5000.00")


def test_parsed_amount_is_decimal_not_float() -> None:
    request = parse_request("Buy ₦5,000 MTN airtime for 08030000001")

    assert isinstance(request.amount, Decimal)
    assert not isinstance(request.amount, float)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Buy ₦500 MTN airtime for 08030000001", Decimal("500.00")),
        ("Buy ₦5000 MTN airtime for 08030000001", Decimal("5000.00")),
        ("Buy ₦50000 MTN airtime for 08030000001", Decimal("50000.00")),
        ("Buy ₦500,000 MTN airtime for 08030000001", Decimal("500000.00")),
        ("Buy ₦1,250.75 MTN airtime for 08030000001", Decimal("1250.75")),
        ("Buy 5000 MTN airtime for 08030000001", Decimal("5000.00")),
        ("Buy NGN 5000 MTN airtime for 08030000001", Decimal("5000.00")),
        ("Buy ₦5,000.00 MTN airtime for 08030000001", Decimal("5000.00")),
    ],
)
def test_amount_regression_exact_decimal_values(text: str, expected: Decimal) -> None:
    """Ungrouped and grouped amounts must never be truncated or regrouped."""
    request = parse_request(text)

    assert isinstance(request.amount, Decimal)
    assert request.amount == expected


def test_fractional_amount_is_preserved() -> None:
    request = parse_request("Buy ₦1,250.75 MTN airtime for 08030000001")

    assert request.amount == Decimal("1250.75")


def test_missing_amount_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy MTN airtime for 08030000001")


def test_request_without_amount_or_beneficiary_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy airtime")


def test_request_without_amount_network_or_beneficiary_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy MTN airtime")


def test_missing_network_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy ₦5000 airtime for 08030000001")


def test_missing_beneficiary_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy ₦5000 MTN airtime")


def test_zero_amount_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy ₦0 MTN airtime for 08030000001")


def test_negative_amount_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy -₦5000 MTN airtime for 08030000001")


def test_unsupported_transaction_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy ₦5000 MTN data for 08030000001")


def test_non_purchase_request_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("What is my balance?")


def test_empty_request_is_rejected() -> None:
    with pytest.raises(UnsupportedRequestError):
        parse_request("   ")


def test_parser_does_not_accept_or_generate_vendor_code() -> None:
    # The AgentRequest model forbids extra fields, so a vendor hint in the
    # text must not leak into the structured request.
    request = parse_request("Buy ₦5,000 MTN airtime for 08030000001 via vendor_b")

    assert "vendor_code" not in request.model_fields_set
    assert request.model_dump().get("vendor_code") is None


def test_parser_module_direct_imports_are_restricted() -> None:
    # The parser itself may import only the standard library and AgentRequest.
    # It must not directly import vendors, switcher, policy, MCP, database,
    # SQLAlchemy, or HTTP client layers.
    import ast
    from pathlib import Path

    import agent.request_understanding as parser_module

    source = Path(parser_module.__file__).read_text(encoding="utf-8")

    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module)

    assert imported <= {"__future__", "re", "decimal", "agent.runtime.service"}


def test_parser_is_side_effect_free() -> None:
    # Parsing must not import or initialize any execution, policy, vendor,
    # MCP, or database layer: the set of loaded modules must not grow while
    # the parser runs.
    import sys

    # Warm any lazily-imported model internals before taking the snapshot.
    parse_request("Buy ₦5,000 MTN airtime for 08030000001")
    before = set(sys.modules)

    parse_request("Buy ₦500 MTN airtime for 08030000001")
    parse_request("Buy 50000 MTN airtime for 08030000001")
    with pytest.raises(UnsupportedRequestError):
        parse_request("Buy airtime")

    assert set(sys.modules) - before == set()


def test_fresh_import_of_parser_does_not_load_execution_layers() -> None:
    # In a clean interpreter, importing the parser must not pull in vendors,
    # SQLAlchemy, the database module, or external HTTP clients. (The
    # AgentRequest contract lives in agent.runtime.service, which the parser
    # is explicitly allowed to import.)
    import subprocess
    import sys
    from pathlib import Path

    import agent.request_understanding as parser_module

    repo_root = Path(parser_module.__file__).parents[1]
    script = (
        "import sys\n"
        "import agent.request_understanding\n"
        "forbidden = ('vendors', 'sqlalchemy', 'apps.api.app.database',"
        " 'redis', 'kafka', 'aiohttp', 'requests')\n"
        "loaded = [n for n in sys.modules"
        " if n.split('.')[0] in forbidden]\n"
        "print(loaded)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=True,
    )
    assert completed.stdout.strip() == "[]"


def test_class_based_boundary_matches_function() -> None:
    text = "Buy ₦5,000 MTN airtime for 08030000001"
    assert RequestUnderstanding().parse(text).model_dump() == parse_request(text).model_dump()