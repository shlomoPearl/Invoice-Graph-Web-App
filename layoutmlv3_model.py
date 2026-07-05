from transformers import pipeline
from PIL import Image


def make_word_boxes(words: list[str]) -> list:
    """
    Assign sequential fake positions to words so the model's spatial
    attention has meaningful layout to work with.
    Simulates words flowing left-to-right, wrapping at page_width=1000.
    """
    boxes = []
    x, y = 0, 0
    w, h = 50, 20      # approximate word width/height
    page_width = 1000
    for word in words:
        x1 = min(x + w, page_width)
        boxes.append([word, [x, y, x1, y + h]])
        x += w + 10
        if x >= page_width:
            x = 0
            y += h + 5
    return boxes


class LayoutModel:
    def __init__(self, threshold: float = 0.5, questions: list[str] | None = None, date_questions: list[str] | None = None, parse_key: str | None = None):
        print("Loading LayoutLMv3 model...")
        self._qa_pipeline = pipeline(
            "document-question-answering",
            model="impira/layoutlm-document-qa",
            device=-1)
        print("Model loaded.")
        self._confidence_threshold = threshold
        self.questions = questions or [
            "What is the total amount to pay?",
            "What is the total amount due?",
            "What is the grand total?",
            "What is the final total?",
            "What is the amount?"
        ]
        self.date_questions = date_questions or [
            "What is the invoice date?",
        "What is the billing date?",
        "What is the order date?",
        "What is the date?"
        ]
        self._parse_key = parse_key

    def build_questions(self) -> list[str]:
        if self._parse_key:
            return [template.format(category=self._parse_key) for template in self.questions]
        else:
            return self.questions


    def ask_layoutlm_image(self, image: Image.Image) -> float | None:
        """
        PDF path: run document-QA on a PIL image.
        LayoutLMv3 uses the visual layout + embedded text to find amounts.
        Returns the best confident amount, or None if nothing passes the threshold.
        """
        questions = self.build_questions()
        res = []
        for question in questions:
            try:
                results = self._qa_pipeline(image, question)
                top = results[0] if isinstance(results, list) else results
                score = top.get("score", 0.0)
                answer = top.get("answer", "")
                print(f"  Q: '{question}' → A: '{answer}' (score {score:.6f})")
                res.append((answer, score))
            except Exception as e:
                # if "OCR" not in str(e):
                print(f"LayoutLMv3 image-mode error on '{question}': {e}")
        return res
    

    def ask_layoutlm_text(self, text: str) -> float | None:
        """
        HTML path: feed plain text directly with dummy bounding boxes.
        Avoids image rendering and OCR entirely — HTML is already clean text.
        word_boxes format: [[word, [x0, y0, x1, y1]], ...] with coords 0-1000.
        Dummy coords are fine here since we care about content not layout.
        """
        words = text.split()
        if not words:
            return None
        word_boxes = make_word_boxes(words)

        questions = self.build_questions()
        amount_res = []
        date_res = []
        for question in questions:
            try:
                amount_results = self._qa_pipeline({"question": question, "word_boxes": word_boxes})
                top = amount_results[0] if isinstance(amount_results, list) else amount_results
                score = top.get("score", 0.0)
                answer = top.get("answer", "")
                print(f"  Q: '{question}' → A: '{answer}' (score {score:.6f})")
                amount_res.append((answer, score))
            except Exception as e:
                print(f"LayoutLMv3 text-mode error on '{question}': {e}")
        for question in self.date_questions:
            try:
                date_results = self._qa_pipeline({"question": question, "word_boxes": word_boxes})
                top = date_results[0] if isinstance(date_results, list) else date_results
                score = top.get("score", 0.0)
                answer = top.get("answer", "")
                print(f"  Q: '{question}' → A: '{answer}' (score {score:.6f})")
                date_res.append((answer, score))
            except Exception as e:
                print(f"LayoutLMv3 text-mode error on DateQ'{question}': {e}")
        return amount_res, date_res
