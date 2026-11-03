from unittest.mock import MagicMock
import pytest
from layoutmlv3_model import make_word_boxes, LayoutModel


def make_layout_model(threshold=0.5, questions=None, date_questions=None, parse_key=None):
    """Construct a LayoutModel without running __init__ (avoids real HF pipeline load)."""
    lm = object.__new__(LayoutModel)
    lm._qa_pipeline = MagicMock()
    lm._confidence_threshold = threshold
    lm.questions = questions if questions is not None else [
        "What is the total amount to pay?",
        "What is the total amount due?",
    ]
    lm.date_questions = date_questions if date_questions is not None else ["What is the invoice date?"]
    lm._parse_key = parse_key
    return lm


class TestMakeWordBoxes:
    def test_empty_list(self):
        assert make_word_boxes([]) == []

    def test_single_word_starts_at_origin(self):
        boxes = make_word_boxes(["Total"])
        assert boxes == [["Total", [0, 0, 50, 20]]]

    def test_multiple_words_advance_x_by_width_plus_gap(self):
        boxes = make_word_boxes(["A", "B"])
        assert boxes[0] == ["A", [0, 0, 50, 20]]
        assert boxes[1] == ["B", [60, 0, 110, 20]]

    def test_wraps_to_next_row_at_page_width(self):
        # width+gap = 60 per word; the 17th word (index 16) reaches x=960
        # and gets clamped to x1=1000, then triggers the wrap for the *next*
        # word. So word index 17 (the 18th word) is the first one placed
        # on the new row at y=25, x=0.
        words = [f"w{i}" for i in range(18)]
        boxes = make_word_boxes(words)
        last_word, last_box = boxes[-1]
        assert last_box[1] == 25  # y wrapped down one row (h=20, +5 gap)
        assert last_box[0] == 0   # x reset to 0 after wrap

    def test_box_x1_clamped_to_page_width(self):
        # Construct a case where x + w would exceed page_width=1000 before wrap check
        words = [f"w{i}" for i in range(20)]
        boxes = make_word_boxes(words)
        for _, (x0, y0, x1, y1) in boxes:
            assert x1 <= 1000

    def test_preserves_word_order(self):
        words = ["Total", "Amount", "Due"]
        boxes = make_word_boxes(words)
        assert [b[0] for b in boxes] == words


class TestBuildQuestions:
    def test_no_parse_key_returns_questions_unmodified(self):
        lm = make_layout_model(questions=["What is the total?"], parse_key=None)
        assert lm.build_questions() == ["What is the total?"]

    def test_parse_key_formats_category_templates(self):
        lm = make_layout_model(
            questions=["What is the {category} fee?", "How much is {category}?"],
            parse_key="water",
        )
        assert lm.build_questions() == [
            "What is the water fee?",
            "How much is water?",
        ]

    def test_empty_string_parse_key_treated_as_falsy(self):
        # `if self._parse_key:` -- an empty string is falsy, so questions
        # pass through unformatted rather than raising a KeyError on
        # templates containing "{category}".
        lm = make_layout_model(questions=["Plain question"], parse_key="")
        assert lm.build_questions() == ["Plain question"]


def _pipeline_response(answer, score):
    return {"answer": answer, "score": score}


class TestAskLayoutlmImage:
    def test_returns_amount_and_date_results_per_question(self):
        lm = make_layout_model(
            questions=["Q amount 1", "Q amount 2"],
            date_questions=["Q date 1"],
        )
        lm._qa_pipeline.side_effect = [
            _pipeline_response("100.00", 0.9),
            _pipeline_response("200.00", 0.3),
            _pipeline_response("March 2024", 0.8),
        ]
        amount_res, date_res = lm.ask_layoutlm_image(image="fake-image")
        assert amount_res == [("100.00", 0.9), ("200.00", 0.3)]
        assert date_res == [("March 2024", 0.8)]

    def test_handles_list_shaped_pipeline_response(self):
        lm = make_layout_model(questions=["Q1"], date_questions=[])
        lm._qa_pipeline.return_value = [_pipeline_response("50.00", 0.7)]
        amount_res, date_res = lm.ask_layoutlm_image(image="fake-image")
        assert amount_res == [("50.00", 0.7)]
        assert date_res == []

    def test_per_question_exception_does_not_abort_remaining_questions(self):
        lm = make_layout_model(questions=["Q1", "Q2"], date_questions=[])
        lm._qa_pipeline.side_effect = [
            RuntimeError("OCR failed"),
            _pipeline_response("75.00", 0.6),
        ]
        amount_res, date_res = lm.ask_layoutlm_image(image="fake-image")
        assert amount_res == [("75.00", 0.6)]

    def test_all_questions_fail_returns_empty_lists(self):
        lm = make_layout_model(questions=["Q1"], date_questions=["QD1"])
        lm._qa_pipeline.side_effect = RuntimeError("boom")
        amount_res, date_res = lm.ask_layoutlm_image(image="fake-image")
        assert amount_res == []
        assert date_res == []


class TestAskLayoutlmText:
    def test_empty_text_returns_none(self):
        lm = make_layout_model()
        assert lm.ask_layoutlm_text("") is None

    def test_whitespace_only_text_returns_none(self):
        lm = make_layout_model()
        assert lm.ask_layoutlm_text("   ") is None

    def test_returns_amount_and_date_results(self):
        lm = make_layout_model(questions=["Q1"], date_questions=["QD1"])
        lm._qa_pipeline.side_effect = [
            _pipeline_response("120.00", 0.95),
            _pipeline_response("April 2024", 0.85),
        ]
        amount_res, date_res = lm.ask_layoutlm_text("Total amount due 120.00")
        assert amount_res == [("120.00", 0.95)]
        assert date_res == [("April 2024", 0.85)]

    def test_calls_pipeline_with_word_boxes_payload(self):
        lm = make_layout_model(questions=["Q1"], date_questions=[])
        lm._qa_pipeline.return_value = _pipeline_response("10.00", 0.5)
        lm.ask_layoutlm_text("hello world")
        call_kwargs = lm._qa_pipeline.call_args[0][0]
        assert call_kwargs["question"] == "Q1"
        assert call_kwargs["word_boxes"][0][0] == "hello"

    def test_per_question_exception_does_not_abort_remaining_questions(self):
        lm = make_layout_model(questions=["Q1", "Q2"], date_questions=[])
        lm._qa_pipeline.side_effect = [
            _pipeline_response("30.00", 0.4),
            RuntimeError("pipeline error"),
        ]
        amount_res, date_res = lm.ask_layoutlm_text("some text here")
        assert amount_res == [("30.00", 0.4)]