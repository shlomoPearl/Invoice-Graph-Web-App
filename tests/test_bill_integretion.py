from io import BytesIO
from unittest.mock import MagicMock

import pytest
from reportlab.pdfgen import canvas

from bill import ReadBill


def make_read_bill(currency_symbols=("$",), parse_key=None, date_data_dict=None):
    rb = object.__new__(ReadBill)
    rb.date_data_dict = date_data_dict or {}
    rb.currency_symbols = currency_symbols
    rb.parse_key = parse_key
    rb.ML_model = MagicMock()
    return rb


def ml_response(amount_answer, amount_score, date_answer, date_score):
    amounts = [(amount_answer, amount_score)] if amount_answer is not None else []
    dates = [(date_answer, date_score)] if date_answer is not None else []
    return amounts, dates


def make_pdf_bytes(pages_text):
    buf = BytesIO()
    c = canvas.Canvas(buf)
    for text in pages_text:
        c.drawString(50, 750, text)
        c.showPage()
    c.save()
    return buf.getvalue()


class TestParseHtmlHappyPath:
    def test_confident_amount_and_date_skips_regex_fallback(self):
        rb = make_read_bill()
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            "150.00", 0.9, "March 2024", 0.9
        )
        html = "<html><body><p>Total: $150.00</p></body></html>"
        amount, date = rb._parse_html(html)
        assert amount == 150.00
        assert date == "03/2024"

    def test_parse_key_is_forwarded_to_ml_questions_indirectly(self):
        # We can't inspect the exact question text sent to a mocked pipeline
        # here (that's covered in test_layoutmlv3_model.py). Testing this via
        # _parse_html directly isn't possible when the ML amount isn't
        # confident, since that path hits the float/tuple bug documented in
        # TestParseHtmlKnownBugs -- so we verify parse_key forwarding at the
        # regex fallback method itself instead.
        rb = make_read_bill(parse_key="Water")
        html = "<html><body><p>Water</p><p>$75.00</p></body></html>"
        amount = rb._html_regex_fallback(html, parse_key="Water")
        assert amount == 75.00


class TestParseHtmlKnownBugs:
    def test_none_date_crashes_parse_date_even_with_confident_amount(self):
        """
        KNOWN BUG: `_parse_html` calls `best_date = parse_date(best_date)`
        unconditionally, before checking whether `best_amount` is usable.
        If the ML model finds no confident date at all (dates == []),
        `best_date` stays None, and `parse_date(None)` crashes with
        AttributeError since parse_date does `date_str.lower()` with no
        None-guard. This happens even when the amount WAS extracted
        confidently -- a good amount is thrown away by an unrelated date
        parsing crash.

        This test pins down the current (broken) behavior. Fix candidates:
        guard `parse_date` against None input, or only call it when
        `best_date is not None`.
        """
        rb = make_read_bill()
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            "150.00", 0.9, None, 0.0
        )
        html = "<html><body><p>Total: $150.00</p></body></html>"
        with pytest.raises(AttributeError):
            rb._parse_html(html)

    def test_regex_fallback_returns_float_not_tuple(self):
        """
        KNOWN BUG: when the ML model isn't confident about the amount,
        `_parse_html` returns `self._html_regex_fallback(...)` directly,
        which is a bare float -- not the `(amount, date)` tuple the rest of
        the code expects. `ReadBill.parser()` does
        `current_total, extracted_date = self._parse_html(...)`, which will
        raise TypeError trying to unpack a float. In `parser()` this is
        silently caught and logged (see TestParserExceptionIsolation below),
        silently dropping that attachment's amount from the result -- a
        confident regex-extracted total is lost with no visible error to
        the caller.
        """
        rb = make_read_bill()
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            None, 0.0, "March 2024", 0.9
        )
        html = "<html><body><p>Total: $150.00</p></body></html>"
        result = rb._parse_html(html)
        assert isinstance(result, float)  # NOT a (amount, date) tuple
        assert result == 150.00


# ---------------------------------------------------------------------------
# _parse_pdf
# ---------------------------------------------------------------------------

class TestParsePdfHappyPath:
    def test_single_page_confident_amount_and_date(self):
        rb = make_read_bill()
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            "99.99", 0.9, "April 2024", 0.9
        )
        pdf_bytes = make_pdf_bytes(["Total: $99.99"])
        total, date = rb._parse_pdf(pdf_bytes)
        assert total == pytest.approx(99.99)
        assert date == "04/2024"

    def test_multi_page_all_confident_sums_correctly(self):
        rb = make_read_bill()
        rb.ML_model.ask_layoutlm_text.side_effect = [
            ml_response("100.00", 0.9, "January 2024", 0.9),
            ml_response("50.00", 0.9, "January 2024", 0.9),
        ]
        pdf_bytes = make_pdf_bytes(["Total: $100.00", "Total: $50.00"])
        total, date = rb._parse_pdf(pdf_bytes)
        assert total == pytest.approx(150.00)

    def test_pdf2image_failure_falls_back_to_whole_document_regex(self):
        rb = make_read_bill()
        pdf_bytes = make_pdf_bytes(["Total: $42.00"])
        # Simulate convert_from_bytes raising (e.g. poppler missing/corrupt PDF)
        import bill as bill_module
        original = bill_module.convert_from_bytes
        bill_module.convert_from_bytes = MagicMock(side_effect=Exception("poppler error"))
        try:
            result = rb._parse_pdf(pdf_bytes)
        finally:
            bill_module.convert_from_bytes = original
        # NOTE: on this path _parse_pdf returns the bare float from
        # _pdf_page_regex_fallback, not a (total, date) tuple -- same shape
        # inconsistency documented for the HTML path above.
        assert isinstance(result, float)
        assert result == pytest.approx(42.00)


class TestParsePdfKnownBugs:
    def test_none_date_crashes_even_with_confident_amount(self):
        """Same root cause as the HTML case: parse_date(None) crashes."""
        rb = make_read_bill()
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            "99.99", 0.9, None, 0.0
        )
        pdf_bytes = make_pdf_bytes(["Total: $99.99"])
        with pytest.raises(AttributeError):
            rb._parse_pdf(pdf_bytes)

    def test_partial_page_fallback_double_counts_whole_document(self):
        """
        KNOWN BUG: when a given page's ML result isn't confident, `_parse_pdf`
        falls back via `self._pdf_page_regex_fallback(data, parse_key)` --
        but `data` is the ENTIRE PDF's bytes, not just the current page. This
        means the regex fallback re-scans and sums amounts from every page,
        including ones that already contributed a confident ML total earlier
        in the same loop -- double-counting them.

        Concretely: page 1 ($100) is confidently extracted via ML. Page 2's
        ML result is not confident, so the code falls back to regex over the
        WHOLE document, re-adding $100 (page 1) + $50 (page 2) = $150 on top
        of the $100 already added. Expected correct total: $150. Actual: $250.
        """
        rb = make_read_bill()
        rb.ML_model.ask_layoutlm_text.side_effect = [
            ml_response("100.00", 0.9, "January 2024", 0.9),  # page 1: confident
            ml_response(None, 0.0, "January 2024", 0.9),       # page 2: not confident
        ]
        pdf_bytes = make_pdf_bytes(["Total: $100.00", "Total: $50.00"])
        total, date = rb._parse_pdf(pdf_bytes)

        # This asserts the CURRENT (buggy) behavior, not the correct one.
        assert total == pytest.approx(250.00)
        # The correct expected value, once fixed, would be:
        # assert total == pytest.approx(150.00)


# ---------------------------------------------------------------------------
# parser() — full dict aggregation across dates/attachments
# ---------------------------------------------------------------------------

class TestParserAggregation:
    def test_single_html_attachment_happy_path(self):
        rb = make_read_bill(
            date_data_dict={"01/2024": ["<html><body>Total: $100.00</body></html>"]}
        )
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            "100.00", 0.9, "January 2024", 0.9
        )
        result = rb.parser()
        assert result == {"01/2024": pytest.approx(100.00)}

    def test_ml_extracted_date_overrides_email_date_as_dict_key(self):
        # The email arrived dated "01/2024", but the ML model confidently
        # extracts "March 2024" from the invoice itself -- parser() should
        # key the result by the extracted date, not the email date.
        rb = make_read_bill(
            date_data_dict={"01/2024": ["<html><body>Total: $100.00</body></html>"]}
        )
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            "100.00", 0.9, "March 2024", 0.9
        )
        result = rb.parser()
        assert result == {"03/2024": pytest.approx(100.00)}
        assert "01/2024" not in result

    def test_multiple_attachments_same_extracted_date_sum_together(self):
        rb = make_read_bill(
            date_data_dict={
                "01/2024": [
                    "<html><body>Total: $100.00</body></html>",
                    "<html><body>Total: $50.00</body></html>",
                ]
            }
        )
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            "100.00", 0.9, "January 2024", 0.9
        )
        # both attachments will independently resolve to the same amount/date
        # via the mocked model regardless of their actual differing content --
        # that's fine, we're testing dict-summing behavior, not extraction
        # accuracy across distinct attachments here.
        result = rb.parser()
        assert result == {"01/2024": pytest.approx(200.00)}

    def test_mixed_pdf_and_html_attachments_across_different_dates(self):
        pdf_bytes = make_pdf_bytes(["Total: $75.00"])
        rb = make_read_bill(
            date_data_dict={
                "01/2024": ["<html><body>Total: $100.00</body></html>"],
                "02/2024": [pdf_bytes],
            }
        )
        rb.ML_model.ask_layoutlm_text.side_effect = [
            ml_response("100.00", 0.9, "January 2024", 0.9),   # HTML
            ml_response("75.00", 0.9, "February 2024", 0.9),   # PDF page 1
        ]
        result = rb.parser()
        assert result == {
            "01/2024": pytest.approx(100.00),
            "02/2024": pytest.approx(75.00),
        }


class TestParserExceptionIsolation:
    def test_one_bad_attachment_does_not_crash_processing_of_others(self):
        """
        parser() wraps each attachment's processing in a broad try/except,
        so a failure on one (e.g. the None-date crash, or corrupt data)
        should not prevent other, valid attachments from being processed.
        """
        rb = make_read_bill(
            date_data_dict={
                "01/2024": ["<html><body>Total: $999.00</body></html>"],  # will crash (no date)
                "02/2024": ["<html><body>Total: $50.00</body></html>"],   # should succeed
            }
        )
        rb.ML_model.ask_layoutlm_text.side_effect = [
            ml_response("999.00", 0.9, None, 0.0),          # 01/2024: triggers None-date crash
            ml_response("50.00", 0.9, "February 2024", 0.9),  # 02/2024: happy path
        ]
        result = rb.parser()
        # The crashing attachment contributes nothing; the healthy one does.
        assert "01/2024" not in result
        assert result.get("02/2024") == pytest.approx(50.00)

    def test_corrupt_pdf_bytes_does_not_crash_parser(self):
        rb = make_read_bill(
            date_data_dict={"01/2024": [b"not a real pdf at all"]}
        )
        # ML model won't even be reached if pdf2image/PyPDF2 fail first,
        # but parser() should still return cleanly either way.
        rb.ML_model.ask_layoutlm_text.return_value = ml_response(
            None, 0.0, None, 0.0
        )
        result = rb.parser()
        assert isinstance(result, dict)

    def test_empty_date_data_dict_returns_empty_bill_dict(self):
        rb = make_read_bill(date_data_dict={})
        assert rb.parser() == {}