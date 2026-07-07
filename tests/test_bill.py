import pytest
from bill import (
    ReadBill,
    clean_amount_string,
    extract_amount_from_answer,
)


def make_read_bill(currency_symbols=("$", "₪", "€"), parse_key=None):
    """Construct a ReadBill without running __init__ (avoids LayoutModel load)."""
    rb = object.__new__(ReadBill)
    rb.date_data_dict = {}
    rb.currency_symbols = currency_symbols
    rb.parse_key = parse_key
    return rb


class TestCleanAmountString:
    def test_plain_decimal(self):
        assert clean_amount_string("123.45") == 123.45

    def test_comma_formatted(self):
        assert clean_amount_string("1,234.56") == 1234.56

    def test_integer_no_decimal(self):
        assert clean_amount_string("500") == 500.0

    def test_none_input(self):
        assert clean_amount_string(None) is None

    def test_empty_string(self):
        assert clean_amount_string("") is None

    def test_non_numeric_garbage(self):
        assert clean_amount_string("abc") is None

    def test_whitespace_padded(self):
        assert clean_amount_string("  99.99  ") == 99.99


class TestExtractAmountFromAnswer:
    def test_currency_prefix_stripped(self):
        assert extract_amount_from_answer("$1,234.56") == 1234.56

    def test_currency_and_trailing_text(self):
        assert extract_amount_from_answer("Total: 250.00 USD") == 250.0

    def test_stray_digits_elsewhere_in_string_corrupt_the_amount(self):
        assert extract_amount_from_answer("Total 250.00 (page 2)") == 250.002

    def test_none_input(self):
        assert extract_amount_from_answer(None) is None

    def test_no_digits_present(self):
        assert extract_amount_from_answer("no amount here") is None

    def test_shekel_symbol(self):
        assert extract_amount_from_answer("₪450.00") == 450.00


class TestExtractAmountsFromLine:
    def test_symbol_before_amount(self):
        rb = make_read_bill()
        assert rb._extract_amounts_from_line("Total: $123.45") == [123.45]

    def test_symbol_after_amount(self):
        rb = make_read_bill()
        assert rb._extract_amounts_from_line("Total: 123.45$") == [123.45]

    def test_multiple_amounts_same_line(self):
        rb = make_read_bill()
        result = rb._extract_amounts_from_line("Subtotal $10.00 Tax $2.00")
        assert result == [10.00, 2.00]

    def test_comma_formatted_amount(self):
        rb = make_read_bill()
        assert rb._extract_amounts_from_line("Total: $1,250.00") == [1250.00]

    def test_no_currency_symbol_present(self):
        rb = make_read_bill()
        assert rb._extract_amounts_from_line("Just some text 123.45") == []

    def test_parse_key_filters_non_matching_line(self):
        rb = make_read_bill(parse_key="water")
        assert rb._extract_amounts_from_line("Electricity: $50.00", parse_key="water") == []

    def test_parse_key_matches_case_insensitively(self):
        rb = make_read_bill()
        result = rb._extract_amounts_from_line("WATER charge: $50.00", parse_key="water")
        assert result == [50.00]

    def test_no_parse_key_matches_any_line(self):
        rb = make_read_bill()
        result = rb._extract_amounts_from_line("Water charge: $50.00", parse_key=None)
        assert result == [50.00]


class TestHtmlRegexFallback:
    def test_finds_total_line_no_parse_key(self):
        rb = make_read_bill()
        html = "<html><body><p>Total: $150.00</p></body></html>"
        assert rb._html_regex_fallback(html) == 150.00

    def test_sums_multiple_currency_lines_when_no_parse_key(self):
        rb = make_read_bill()
        html = "<html><body><p>Item A: $10.00</p><p>Item B: $20.00</p></body></html>"
        assert rb._html_regex_fallback(html) == 30.00

    def test_parse_key_finds_amount_on_next_line(self):
        rb = make_read_bill()
        html = "<html><body><p>Water</p><p>$75.50</p></body></html>"
        assert rb._html_regex_fallback(html, parse_key="Water") == 75.50

    def test_parse_key_not_found_returns_zero(self):
        rb = make_read_bill()
        html = "<html><body><p>Electricity: $50.00</p></body></html>"
        assert rb._html_regex_fallback(html, parse_key="Water") == 0.0

    def test_no_amounts_at_all_returns_zero(self):
        rb = make_read_bill()
        html = "<html><body><p>No amounts here.</p></body></html>"
        assert rb._html_regex_fallback(html) == 0.0

    def test_empty_html(self):
        rb = make_read_bill()
        assert rb._html_regex_fallback("") == 0.0


class TestPdfPageRegexFallback:
    def _make_pdf_bytes(self, lines_per_page):
        """Build a minimal real PDF (via reportlab) with given lines per page."""
        from reportlab.pdfgen import canvas
        from io import BytesIO

        buf = BytesIO()
        c = canvas.Canvas(buf)
        for page_lines in lines_per_page:
            y = 750
            for line in page_lines:
                c.drawString(50, y, line)
                y -= 20
            c.showPage()
        c.save()
        return buf.getvalue()

    def test_single_page_extracts_total(self):
        rb = make_read_bill()
        pdf_bytes = self._make_pdf_bytes([["Invoice", "Total: $99.99"]])
        assert rb._pdf_page_regex_fallback(pdf_bytes) == pytest.approx(99.99)

    def test_multi_page_sums_across_pages(self):
        rb = make_read_bill()
        pdf_bytes = self._make_pdf_bytes([
            ["Page 1 Total: $10.00"],
            ["Page 2 Total: $20.00"],
        ])
        assert rb._pdf_page_regex_fallback(pdf_bytes) == pytest.approx(30.00)

    def test_parse_key_filters_across_pages(self):
        rb = make_read_bill()
        pdf_bytes = self._make_pdf_bytes([
            ["Water charge: $40.00"],
            ["Electricity charge: $60.00"],
        ])
        assert rb._pdf_page_regex_fallback(pdf_bytes, parse_key="Water") == pytest.approx(40.00)

    def test_page_with_no_extractable_text_is_skipped(self):
        rb = make_read_bill()
        # A page with only a drawn line/shape (no text) still parses without error
        from reportlab.pdfgen import canvas
        from io import BytesIO
        buf = BytesIO()
        c = canvas.Canvas(buf)
        c.line(0, 0, 10, 10)  # no text at all
        c.showPage()
        c.save()
        assert rb._pdf_page_regex_fallback(buf.getvalue()) == 0.0

    def test_corrupt_pdf_bytes_returns_zero_not_raise(self):
        rb = make_read_bill()
        assert rb._pdf_page_regex_fallback(b"this is not a pdf") == 0.0