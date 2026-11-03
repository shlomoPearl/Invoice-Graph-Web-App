import pytest
from date_op import date_in_range, parse_date, increment_date, decrement_date, get_date


class TestParseDate:
    def test_full_month_name_and_year(self):
        assert parse_date("March 2024") == "03/2024"

    def test_full_month_name_lowercase(self):
        assert parse_date("december 2023") == "12/2023"

    def test_abbreviated_month_name(self):
        assert parse_date("Mar 2024") == "03/2024"

    def test_month_name_embedded_in_sentence(self):
        assert parse_date("Invoice for January 2022 billing period") == "01/2022"

    def test_yyyy_mm_dd_slash(self):
        assert parse_date("2024/03/15") == "03/2024"

    def test_yyyy_mm_dd_dash(self):
        assert parse_date("2024-03-15") == "03/2024"

    def test_mm_dd_yyyy_slash(self):
        assert parse_date("03/15/2024") == "03/2024"

    def test_mm_dd_yyyy_dash(self):
        assert parse_date("03-15-2024") == "03/2024"

    def test_mm_yyyy(self):
        assert parse_date("03/2024") == "03/2024"

    def test_single_digit_month_yyyy(self):
        assert parse_date("3/2024") == "03/2024"

    def test_mm_yy_short_year(self):
        assert parse_date("03/24") == "03/2024"
        assert parse_date("12/24") == "12/2024"

    def test_yy_mm_short_year(self):
        assert parse_date("24/03") == "03/2024"
        assert parse_date("24/12") == "12/2024"

    def test_dd_mm_yy(self):
        assert parse_date("15/03/24") == "03/2024"
        assert parse_date("01/12/24") == "12/2024"

    def test_full_date_not_misparsed_as_mm_yyyy(self):
        assert parse_date("03/15/2024") == "03/2024"

    def test_garbage_input_returns_none(self):
        assert parse_date("not a date") is None

    def test_empty_string_returns_none(self):
            assert parse_date("") is None

    def test_only_year_returns_none(self):
        assert parse_date("2024") is None

    def test_invalid_date(self):
        print(parse_date("31/02/2024"))
        assert parse_date("31/02/2024") == None
        assert parse_date("30/02/2024") == None
        assert parse_date("31/04/2023") == None
        assert parse_date("32/09/2023") == None


class TestIncrementDate:
    def test_normal_month_increment(self):
        assert increment_date("15/03/2024") == "2024/04/15"

    def test_december_rolls_over_to_january_next_year(self):
        assert increment_date("10/12/2024") == "2025/01/10"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            increment_date("2024/03/15")


class TestDecrementDate:
    def test_normal_month_decrement(self):
        date_list = ["15", "Mar", "2024"]
        assert decrement_date(date_list) == "02/2024"

    def test_january_rolls_back_to_december_previous_year(self):
        date_list = ["15", "Jan", "2024"]
        assert decrement_date(date_list) == "12/2023"

class TestGetDate:
    def test_normal_case(self):
        date_list = ["15", "Mar", "2024"]
        assert get_date(date_list) == "03/2024"

    def test_unknown_month_name_returns_zero_month(self):
        date_list = ["15", "Notamonth", "2024"]
        assert get_date(date_list) == None

class TestRangeDate:
    def test_date_in_range(self):
        assert date_in_range("03/2024", "01/2024", "12/2024") == True
        assert date_in_range("01/2024", "01/2024", "12/2024") == True
        assert date_in_range("12/2024", "01/2024", "12/2024") == True

    def test_date_out_of_range_before(self):
        assert date_in_range("12/2023", "01/2024", "12/2024") == False
        assert date_in_range("08/2024", "09/2024", "12/2024") == False

    def test_date_out_of_range_after(self):
        assert date_in_range("01/2025", "01/2024", "12/2024") == False
        assert date_in_range("09/2024", "01/2024", "08/2024") == False

    def test_invalid_date_format(self):
        assert date_in_range("2024/03", "01/2024", "12/2024") == False
        assert date_in_range("03-2024", "01/2024", "12/2024") == False
        assert date_in_range("March 2024", "01/2024", "12/2024") == False