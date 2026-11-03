"""
End-to-end tests: real Chromium browser (via Playwright) driving the actual
running Invoice-Graph stack (docker-compose + docker-compose.e2e.yml), with
only Google OAuth/Gmail stubbed out (see google_stub_app.py). Everything
else -- FastAPI routing, Jinja2 templates, Starlette sessions, real
Postgres, real Gmail search/parsing/graph-rendering code -- runs for real.

Run:
    docker compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yml up -d
    playwright install chromium
    pytest tests/e2e/ -v
"""
import base64
import json
import os

import itsdangerous
import pytest

from conftest import APP_BASE_URL, seed_stub_gmail_data, make_html_invoice_message

SESSION_COOKIE_NAME = "session_id"


def _sign_session_cookie(session_dict: dict) -> str:
    """Craft a valid Starlette SessionMiddleware cookie, using the app's
    real KEY from .env, so we can pre-authenticate a browser context without
    driving a full OAuth handshake for every test that doesn't need one."""
    key = os.getenv("KEY")
    signer = itsdangerous.TimestampSigner(key)
    data = base64.b64encode(json.dumps(session_dict).encode("utf-8"))
    return signer.sign(data).decode("utf-8")


class TestFreshLoginFlow:
    def test_login_then_form_produces_graph(self, page):
        """
        Full cold-start path: no prior session at all. Submitting the form
        redirects through /auth/login -> the (stubbed) Google consent
        screen, which auto-approves -> /oauth2callback -> loading page ->
        graph, driven entirely by a real browser clicking through it.
        """
        seed_stub_gmail_data(
            messages_list={"messages": [{"id": "msg1"}]},
            messages_by_id={
                "msg1": make_html_invoice_message(
                    "msg1", "Mon, 15 Mar 2024 10:00:00 +0000",
                    "<html><body>Total: $321.00</body></html>",
                )
            },
        )

        page.goto(APP_BASE_URL)
        page.fill("#email", "invoices@example.com")
        page.fill("#start_date", "01032024")   # form auto-formats to dd/mm/yyyy as you type
        page.fill("#end_date", "15032024")
        page.click("button[type=submit]")

        # loading.html polls /process_after_oauth and document.write()s the
        # result in place -- wait for the graph heading to actually appear
        # rather than for a specific navigation event.
        page.wait_for_selector("text=Payment History Graph", timeout=15000)
        assert page.is_visible("text=Payment History Graph")


class TestReturningUserFlow:
    def test_valid_session_skips_oauth_entirely(self, page, context, seeded_user):
        """
        A user with a valid, non-expired token in the DB should go straight
        from form submission to the graph -- no redirect through
        /auth/login or the stub's consent screen at all.
        """
        seed_stub_gmail_data(
            messages_list={"messages": [{"id": "msg1"}]},
            messages_by_id={
                "msg1": make_html_invoice_message(
                    "msg1", "Fri, 20 Mar 2024 10:00:00 +0000",
                    "<html><body>Total: $88.50</body></html>",
                )
            },
        )

        context.add_cookies([{
            "name": SESSION_COOKIE_NAME,
            "value": _sign_session_cookie({"session_id": seeded_user}),
            "url": APP_BASE_URL,
        }])

        page.goto(APP_BASE_URL)
        page.fill("#email", "invoices@example.com")
        page.fill("#start_date", "01032024")
        page.fill("#end_date", "31032024")
        page.click("button[type=submit]")

        page.wait_for_selector("text=Payment History Graph", timeout=15000)
        # Never bounced through the login redirect along the way.
        assert "/auth/login" not in page.url


class TestDownloadButtons:
    def test_png_and_pdf_downloads_succeed(self, page, context, seeded_user):
        seed_stub_gmail_data(
            messages_list={"messages": [{"id": "msg1"}]},
            messages_by_id={
                "msg1": make_html_invoice_message(
                    "msg1", "Fri, 20 Mar 2024 10:00:00 +0000",
                    "<html><body>Total: $50.00</body></html>",
                )
            },
        )
        context.add_cookies([{
            "name": SESSION_COOKIE_NAME,
            "value": _sign_session_cookie({"session_id": seeded_user}),
            "url": APP_BASE_URL,
        }])

        page.goto(APP_BASE_URL)
        page.fill("#email", "invoices@example.com")
        page.fill("#start_date", "01032024")
        page.fill("#end_date", "31032024")
        page.click("button[type=submit]")
        page.wait_for_selector("text=Payment History Graph", timeout=15000)

        with page.expect_download() as download_info:
            page.click("text=Download PNG")
        png_download = download_info.value
        assert png_download.suggested_filename == "graph.png"

        with page.expect_download() as download_info:
            page.click("text=Download PDF")
        pdf_download = download_info.value
        assert pdf_download.suggested_filename == "graph.pdf"
