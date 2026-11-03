"""
Unit tests for date_op.py

These are pure functions with no I/O, so this is the base of the pyramid:
fast, isolated, no mocking required.
"""
import pytest
from date_op import parse_date, increment_date, decrement_date, get_date


class TestParseDate:
    # --- "Month Year" format ---
    def test_full_month_name_and_year(self):
        assert parse_date("March 2024") == "03/2024"

    def test_full_month_name_lowercase(self):
        assert parse_date("december 2023") == "12/2023"

    def test_abbreviated_month_name(self):
        assert parse_date("Mar 2024") == "03/2024"

    def test_month_name_embedded_in_sentence(self):
        assert parse_date("Invoice for January 2022 billing period") == "01/2022"

    # --- "yyyy/mm/dd" and "yyyy-mm-dd" ---
    def test_yyyy_mm_dd_slash(self):
        assert parse_date("2024/03/15") == "03/2024"

    def test_yyyy_mm_dd_dash(self):
        assert parse_date("2024-03-15") == "03/2024"

    # --- "mm/dd/yyyy" ---
    def test_mm_dd_yyyy_slash(self):
        assert parse_date("03/15/2024") == "03/2024"

    def test_mm_dd_yyyy_dash(self):
        assert parse_date("03-15-2024") == "03/2024"

    # --- "mm/yyyy" ---
    def test_mm_yyyy(self):
        assert parse_date("03/2024") == "03/2024"

    def test_single_digit_month_yyyy(self):
        assert parse_date("3/2024") == "03/2024"

    # --- "mm/yy" ---
    def test_mm_yy_short_year(self):
        # NOTE: current implementation returns the 2-digit year verbatim
        # (e.g. "03/24" and not "03/2024"). This documents current behavior;
        # flag as a possible bug if 4-digit years are expected everywhere downstream.
        assert parse_date("03/24") == "03/24"

    # --- Ambiguity: mm/dd/yyyy should be tried before mm/yyyy ---
    def test_full_date_not_misparsed_as_mm_yyyy(self):
        # "03/15/2024" must match the mm/dd/yyyy branch, not accidentally
        # get truncated/misread as mm/yyyy
        assert parse_date("03/15/2024") == "03/2024"

    # --- Unparseable input ---
    def test_garbage_input_returns_none(self):
        assert parse_date("not a date") is None

    def test_empty_string_returns_none(self):
        assert parse_date("") is None

    def test_only_year_returns_none(self):
        assert parse_date("2024") is None


class TestIncrementDate:
    def test_normal_month_increment(self):
        assert increment_date("15/03/2024") == "2024/04/15"

    def test_december_rolls_over_to_january_next_year(self):
        assert increment_date("10/12/2024") == "2025/01/10"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            increment_date("2024/03/15")

    def test_month_end_date_produces_invalid_calendar_date_known_bug(self):
        """
        KNOWN BUG, found while building the E2E test suite: `increment_date`
        naively does `month += 1` and keeps the original `day` unchanged,
        with no check that the resulting day actually exists in the target
        month. For any date on the 29th-31st of a month, incrementing to a
        shorter month produces a calendar date that doesn't exist.

        This matters in practice: `gmail.py`'s `search_mail` feeds the
        user's end_date straight through `increment_date()` into the Gmail
        "before:" search filter. A date range ending on e.g. 31/03 (very
        common -- "give me this month's invoices") produces "before:
        2024/04/31", which is not a real calendar date. It's unclear
        whether Gmail's search parser silently corrects this, ignores the
        filter, or returns unexpected results -- but it's clearly not the
        intended "before April 1st" boundary. This test pins down the
        current (buggy) output; fix candidates include using
        `datetime.date` arithmetic (e.g. via `calendar.monthrange` or
        rolling to the 1st of the *following* month instead of keeping the
        same day number) rather than manual field incrementing.
        """
        assert increment_date("31/03/2024") == "2024/04/31"  # April has no 31st
        assert increment_date("31/01/2024") == "2024/02/31"  # February has no 31st

    def test_invalid_input_date_still_raises(self):
        # Feb 30th was never a valid date to begin with -- strptime's own
        # parsing correctly rejects this before increment_date's month-math
        # bug ever gets a chance to run.
        with pytest.raises(ValueError):
            increment_date("30/02/2024")


class TestDecrementDate:
    def test_normal_month_decrement(self):
        # date_list format mimics email header split: [weekday, day, month_name, year, ...]
        date_list = ["Mon,", "15", "Mar", "2024"]
        assert decrement_date(date_list) == "02/2024"

    def test_january_rolls_back_to_december_previous_year(self):
        date_list = ["Mon,", "15", "Jan", "2024"]
        assert decrement_date(date_list) == "12/2023"

    def test_unknown_month_name_current_behavior(self):
        # KNOWN ISSUE: unknown month name -> _MONTH_NAMES.get(..., 0) - 1 == -1,
        # which does NOT trigger the "< 1" rollover check correctly in spirit
        # (it happens to satisfy month_num < 1, so it rolls back a year and
        # sets month to 12 -- but this silently masks a bad input rather than
        # raising or signaling an error). This test documents current behavior;
        # revisit once a decision is made on how unknown months should be handled.
        date_list = ["Mon,", "15", "Notamonth", "2024"]
        assert decrement_date(date_list) == "12/2023"


class TestGetDate:
    def test_normal_case(self):
        date_list = ["Mon,", "15", "Mar", "2024"]
        assert get_date(date_list) == "03/2024"

    def test_unknown_month_name_returns_zero_month(self):
        date_list = ["Mon,", "15", "Notamonth", "2024"]
        assert get_date(date_list) == "00/2024"
