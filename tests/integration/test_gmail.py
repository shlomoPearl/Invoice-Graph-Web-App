import base64
from unittest.mock import MagicMock
import httplib2
import pytest
from googleapiclient.errors import HttpError

from gmail import Gmail


def make_service(list_response, get_responses=None, attachment_responses=None):
    """
    Build a mocked Gmail API `service` object matching the real chained-call
    shape: service.users().messages().list(...).execute(),
    service.users().messages().get(...).execute(), and
    service.users().messages().attachments().get(...).execute().
    """
    service = MagicMock()
    messages_mock = service.users.return_value.messages.return_value
    messages_mock.list.return_value.execute.return_value = list_response

    get_responses = get_responses or {}

    def get_side_effect(userId, id):
        m = MagicMock()
        m.execute.return_value = get_responses[id]
        return m

    messages_mock.get.side_effect = get_side_effect

    attachment_responses = attachment_responses or {}

    def attachment_side_effect(userId, messageId, id):
        m = MagicMock()
        m.execute.return_value = attachment_responses[id]
        return m

    messages_mock.attachments.return_value.get.side_effect = attachment_side_effect

    return service


def make_message(msg_id, date_header, parts=None, top_level_mime_type=None, top_level_body=None):
    """Build a fake Gmail API message payload."""
    headers = []
    if date_header is not None:
        headers.append({"name": "Date", "value": date_header})
    payload = {"headers": headers}
    if parts is not None:
        payload["parts"] = parts
    if top_level_mime_type is not None:
        payload["mimeType"] = top_level_mime_type
        payload["body"] = top_level_body
    return {"id": msg_id, "payload": payload}


def b64_html_part(html_str):
    encoded = base64.urlsafe_b64encode(html_str.encode("utf-8")).decode("ascii")
    return {"mimeType": "text/html", "body": {"data": encoded}}


def pdf_part(filename, attachment_id):
    return {"filename": filename, "body": {"attachmentId": attachment_id}}


def b64_attachment_data(raw_bytes):
    return {"data": base64.urlsafe_b64encode(raw_bytes).decode("ascii")}


class TestQueryConstruction:
    def test_query_includes_sender_address(self):
        service = make_service({"messages": []})
        gmail = Gmail(address="billing@company.com", subject=None,
                       date_range=["01/03/2024", "15/03/2024"])
        gmail.search_mail(service)

        called_kwargs = service.users.return_value.messages.return_value.list.call_args.kwargs
        assert "from:billing@company.com" in called_kwargs["q"]

    def test_query_includes_subject_when_provided(self):
        service = make_service({"messages": []})
        gmail = Gmail(address="billing@company.com", subject="Water Bill",
                       date_range=["01/03/2024", "15/03/2024"])
        gmail.search_mail(service)

        q = service.users.return_value.messages.return_value.list.call_args.kwargs["q"]
        assert "subject:Water Bill" in q

    def test_query_omits_subject_clause_when_none(self):
        service = make_service({"messages": []})
        gmail = Gmail(address="billing@company.com", subject=None,
                       date_range=["01/03/2024", "15/03/2024"])
        gmail.search_mail(service)

        q = service.users.return_value.messages.return_value.list.call_args.kwargs["q"]
        assert "subject:" not in q

    def test_before_date_is_converted_to_yyyy_mm_dd_and_incremented(self):
        service = make_service({"messages": []})
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "15/03/2024"])
        gmail.search_mail(service)

        q = service.users.return_value.messages.return_value.list.call_args.kwargs["q"]
        assert "before:2024/04/15" in q

    def test_after_date_is_not_converted_known_bug(self):
        """
        KNOWN BUG: `search_mail` passes `self.date_range[0]` directly into
        the "after:" clause without any reformatting, while "before:" is
        correctly run through `increment_date()` (which reformats
        dd/mm/yyyy -> yyyy/mm/dd). Gmail's search operators expect
        yyyy/mm/dd; a raw "after:01/03/2024" is very likely misparsed or
        silently ignored by Gmail's query parser, meaning the lower bound
        of the date range filter may not actually be applied as intended.

        This test pins down the current (buggy) behavior. Fix candidate:
        convert date_range[0] with the same dd/mm/yyyy -> yyyy/mm/dd logic
        used for date_range[1] (minus the +1 month increment).
        """
        service = make_service({"messages": []})
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "15/03/2024"])
        gmail.search_mail(service)

        q = service.users.return_value.messages.return_value.list.call_args.kwargs["q"]
        # Documents current behavior: raw dd/mm/yyyy, NOT reformatted.
        assert "after:01/03/2024" in q
        assert "after:2024/03/01" not in q

    def test_result_num_forwarded_to_max_results(self):
        service = make_service({"messages": []})
        gmail = Gmail(address="a@b.com", subject=None, result_num=10,
                       date_range=["01/03/2024", "15/03/2024"])
        gmail.search_mail(service)

        called_kwargs = service.users.return_value.messages.return_value.list.call_args.kwargs
        assert called_kwargs["maxResults"] == 10


class TestAttachmentExtraction:
    def test_pdf_attachment_is_fetched_and_decoded(self):
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        msg = make_message(
            "msg1", "Mon, 15 Mar 2024 10:00:00 +0000",
            parts=[pdf_part("invoice.pdf", "att1")],
        )
        service = make_service(
            {"messages": [{"id": "msg1"}]},
            get_responses={"msg1": msg},
            attachment_responses={"att1": b64_attachment_data(pdf_bytes)},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert result["03/2024"] == [pdf_bytes]

    def test_html_part_used_when_no_pdf_attachment(self):
        html = "<html><body>Total: $50.00</body></html>"
        msg = make_message(
            "msg1", "Mon, 15 Mar 2024 10:00:00 +0000",
            parts=[b64_html_part(html)],
        )
        service = make_service(
            {"messages": [{"id": "msg1"}]},
            get_responses={"msg1": msg},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert result["03/2024"] == [html]

    def test_pdf_preferred_over_html_when_both_present(self):
        pdf_bytes = b"%PDF-1.4 fake"
        html = "<html>ignored</html>"
        msg = make_message(
            "msg1", "Mon, 15 Mar 2024 10:00:00 +0000",
            parts=[b64_html_part(html), pdf_part("invoice.pdf", "att1")],
        )
        service = make_service(
            {"messages": [{"id": "msg1"}]},
            get_responses={"msg1": msg},
            attachment_responses={"att1": b64_attachment_data(pdf_bytes)},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert result["03/2024"] == [pdf_bytes]

    def test_single_part_html_message_without_parts_key(self):
        html = "<html><body>Total: $25.00</body></html>"
        encoded = base64.urlsafe_b64encode(html.encode("utf-8")).decode("ascii")
        msg = make_message(
            "msg1", "Mon, 15 Mar 2024 10:00:00 +0000",
            top_level_mime_type="text/html",
            top_level_body={"data": encoded},
        )
        service = make_service(
            {"messages": [{"id": "msg1"}]},
            get_responses={"msg1": msg},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert result["03/2024"] == [html]

    def test_message_with_no_matching_content_produces_no_entry(self):
        # A part exists but is neither a PDF nor text/html (e.g. plain text)
        msg = make_message(
            "msg1", "Mon, 15 Mar 2024 10:00:00 +0000",
            parts=[{"mimeType": "text/plain", "body": {"data": "abc"}}],
        )
        service = make_service(
            {"messages": [{"id": "msg1"}]},
            get_responses={"msg1": msg},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert dict(result) == {}


class TestDateGrouping:
    def test_multiple_messages_same_month_accumulate_in_one_list(self):
        html_a = "<html>A: $10</html>"
        html_b = "<html>B: $20</html>"
        msg_a = make_message("msgA", "Mon, 5 Mar 2024 09:00:00 +0000", parts=[b64_html_part(html_a)])
        msg_b = make_message("msgB", "Fri, 20 Mar 2024 09:00:00 +0000", parts=[b64_html_part(html_b)])
        service = make_service(
            {"messages": [{"id": "msgA"}, {"id": "msgB"}]},
            get_responses={"msgA": msg_a, "msgB": msg_b},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert result["03/2024"] == [html_a, html_b]

    def test_messages_in_different_months_produce_separate_keys(self):
        html_a = "<html>A</html>"
        html_b = "<html>B</html>"
        msg_a = make_message("msgA", "Mon, 5 Mar 2024 09:00:00 +0000", parts=[b64_html_part(html_a)])
        msg_b = make_message("msgB", "Fri, 12 Apr 2024 09:00:00 +0000", parts=[b64_html_part(html_b)])
        service = make_service(
            {"messages": [{"id": "msgA"}, {"id": "msgB"}]},
            get_responses={"msgA": msg_a, "msgB": msg_b},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "30/04/2024"])
        result = gmail.search_mail(service)

        assert result["03/2024"] == [html_a]
        assert result["04/2024"] == [html_b]

    def test_missing_date_header_uses_none_as_key(self):
        """
        Documents current behavior: if a message has no 'Date' header,
        `date` stays None, and (if the message has extractable content)
        `date_attachment_dict[None]` is used as a real dict key. This is a
        legitimate way for `bill.py`'s known `parse_date(None)` crash (see
        test_bill_integration.py) to actually get triggered end-to-end, if
        no valid Date header is found and the ML model also can't extract
        a date.
        """
        html = "<html>no date header</html>"
        msg = make_message("msg1", date_header=None, parts=[b64_html_part(html)])
        service = make_service(
            {"messages": [{"id": "msg1"}]},
            get_responses={"msg1": msg},
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert result[None] == [html]


class TestErrorHandlingAndEmptyResults:
    def test_no_messages_returns_empty_dict(self):
        service = make_service({"messages": []})
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert dict(result) == {}

    def test_missing_messages_key_returns_empty_dict(self):
        # Gmail's list API omits the "messages" key entirely when there are
        # zero results, rather than returning an empty list under it.
        service = make_service({"resultSizeEstimate": 0})
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert dict(result) == {}

    def test_http_error_returns_none_known_bug(self):
        """
        KNOWN BUG: when the Gmail API raises HttpError (e.g. rate limiting,
        auth failure mid-request), `search_mail`'s except block only prints
        the error and falls off the end of the function -- there's no
        explicit `return`, so Python implicitly returns None instead of an
        (even empty) dict. Callers (main.py's process_flow ->
        ReadBill(attachments, ...)) then call `.items()` on whatever this
        returns; None has no `.items()`, so a transient Gmail API error
        surfaces to the user as an unrelated AttributeError deep inside
        bill.py rather than a clear "Gmail request failed" message.
        """
        service = MagicMock()
        resp = httplib2.Response({"status": 500})
        resp.reason = "Internal Server Error"
        service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            HttpError(resp, b"rate limit exceeded")
        )
        gmail = Gmail(address="a@b.com", subject=None,
                       date_range=["01/03/2024", "31/03/2024"])
        result = gmail.search_mail(service)

        assert result is None