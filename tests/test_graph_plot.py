"""
Unit tests for graph_plot.py

Both plotly and matplotlib run for real here (no mocking) since they're
deterministic, in-memory rendering libraries with no external I/O -- a good
fit for the unit layer. We assert on structural properties of the output
(valid HTML string, non-empty bytes, correct format) rather than exact
pixel/byte content, since rendering output can vary slightly across library
versions.
"""
import pytest
from graph_plot import GraphPlot


@pytest.fixture
def bill_dict():
    return {"01/2024": 150.0, "02/2024": 200.5, "03/2024": 99.99}


class TestGetHtmlGraph:
    def test_returns_html_string(self, bill_dict):
        graph = GraphPlot(bill_dict)
        html = graph.get_html_graph()
        assert isinstance(html, str)
        assert "<div" in html or "<script" in html  # plotly embeds a div+script

    def test_includes_dates_and_title_in_output(self, bill_dict):
        graph = GraphPlot(bill_dict, title="My Custom Title")
        html = graph.get_html_graph()
        assert "My Custom Title" in html
        for date in bill_dict.keys():
            # plotly's embedded JSON escapes "/" as the unicode sequence
            # \u002f, so the raw date string won't appear verbatim in the
            # generated HTML.
            escaped_date = date.replace("/", "\\u002f")
            assert escaped_date in html

    def test_default_title_used_when_not_provided(self, bill_dict):
        graph = GraphPlot(bill_dict)
        html = graph.get_html_graph()
        assert "Payment Graph" in html

    def test_single_entry_bill_dict(self):
        graph = GraphPlot({"01/2024": 42.0})
        html = graph.get_html_graph()
        assert isinstance(html, str)
        assert "01\\u002f2024" in html

    def test_empty_bill_dict_does_not_raise(self):
        graph = GraphPlot({})
        html = graph.get_html_graph()
        assert isinstance(html, str)

    def test_static_plot_config_disables_mode_bar(self, bill_dict):
        graph = GraphPlot(bill_dict)
        html = graph.get_html_graph()
        # Plotly's to_html embeds the config JSON inline; staticPlot mode
        # disables interactivity, which should surface as "staticPlot":true
        # somewhere in the emitted script config.
        assert "staticPlot" in html


class TestDownloadByF:
    def test_png_returns_nonempty_bytes(self, bill_dict):
        graph = GraphPlot(bill_dict)
        data = graph.download_by_f("png")
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes

    def test_pdf_returns_nonempty_bytes(self, bill_dict):
        graph = GraphPlot(bill_dict)
        data = graph.download_by_f("pdf")
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert data[:4] == b"%PDF"  # PDF magic bytes

    def test_single_entry_bill_dict_does_not_raise(self):
        # Matplotlib bar charts with exactly one bar are a known edge case
        # (bar width/spacing calculations can behave oddly with n=1).
        graph = GraphPlot({"01/2024": 42.0})
        data = graph.download_by_f("png")
        assert len(data) > 0

    def test_unsupported_format_raises(self, bill_dict):
        graph = GraphPlot(bill_dict)
        with pytest.raises(Exception):
            graph.download_by_f("bmp")