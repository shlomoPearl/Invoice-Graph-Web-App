import re
import PyPDF2
from io import BytesIO
from bs4 import BeautifulSoup
from pdf2image import convert_from_bytes
from transformers import pipeline
from PIL import Image
import torch


print("Loading LayoutLMv3 model...")
_qa_pipeline = pipeline(
    "document-question-answering",
    model="impira/layoutlm-document-qa",
    device=0 if torch.cuda.is_available() else -1)
print("Model loaded.")

_CONFIDENCE_THRESHOLD = 0.5
_TOTAL_QUESTIONS = [
    "What is the total amount to pay?",
    "What is the total amount due?",
    "What is the grand total?",
    "What is the final total?",
    "What is the amount?",]
_CATEGORY_QUESTION_TEMPLATES = [
    "What is the amount for {category}?",
    "How much is the {category} charge?",
    "What is the {category} fee?",
    "What is the cost of {category}?",]


def clean_amount_string(amount_str):
    if not amount_str:
        return None
    cleaned = amount_str.replace(',', '').strip()
    try:
        if re.match(r'^\d+\.?\d*$', cleaned):
            return float(cleaned)
    except ValueError:
        pass
    return None


def extract_amount_from_answer(answer_str: str) -> float | None:
    if not answer_str:
        return None
    cleaned = re.sub(r'[^\d,.]', '', answer_str).strip()
    return clean_amount_string(cleaned)


def build_questions(parse_key: str | None) -> list[str]:
    if not parse_key or parse_key.strip().lower() in ("total", ""):
        return _TOTAL_QUESTIONS
    return [t.format(category=parse_key) for t in _CATEGORY_QUESTION_TEMPLATES]


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


def ask_layoutlm_image(image: Image.Image, parse_key: str | None = None) -> float | None:
    """
    PDF path: run document-QA on a PIL image.
    LayoutLMv3 uses the visual layout + embedded text to find amounts.
    Returns the best confident amount, or None if nothing passes the threshold.
    """
    questions = build_questions(parse_key)
    best_amount = None
    best_score = 0.0
    for question in questions:
        try:
            results = _qa_pipeline(image, question)
            top = results[0] if isinstance(results, list) else results
            score = top.get("score", 0.0)
            answer = top.get("answer", "")
            print(f"  Q: '{question}' → A: '{answer}' (score {score:.2f})")
            if score >= _CONFIDENCE_THRESHOLD and score > best_score:
                amount = extract_amount_from_answer(answer)
                if amount is not None:
                    best_amount = amount
                    best_score = score
        except Exception as e:
            print(f"LayoutLMv3 image-mode error on '{question}': {e}")
    return best_amount


def ask_layoutlm_text(text: str, parse_key: str | None = None) -> float | None:
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

    questions = build_questions(parse_key)
    best_amount = None
    best_score = 0.0
    for question in questions:
        try:
            results = _qa_pipeline({"question": question, "word_boxes": word_boxes})
            top = results[0] if isinstance(results, list) else results
            score = top.get("score", 0.0)
            answer = top.get("answer", "")
            print(f"  Q: '{question}' → A: '{answer}' (score {score:.6f})")
            if score > _CONFIDENCE_THRESHOLD and score > best_score:
                amount = extract_amount_from_answer(answer)
                if amount is not None:
                    best_amount = amount
                    best_score = score
        except Exception as e:
            print(f"LayoutLMv3 text-mode error on '{question}': {e}")
    return best_amount


class ReadBill:
    def __init__(self, date_data_dict: dict, currency_symbols):
        self.date_data_dict = date_data_dict
        self.currency_symbols = currency_symbols

    
    def _extract_amounts_from_line(self, line: str, parse_key: str | None = None) -> list[float]:
        amounts = []
        if parse_key and parse_key.lower() not in line.lower():
            return amounts
        currency_pattern = '|'.join(re.escape(sym) for sym in self.currency_symbols)
        pattern = rf'({currency_pattern})\s*([\d,]+\.\d+|\d+)|([\d,]+\.\d+|\d+)\s*({currency_pattern})'
        for match in re.finditer(pattern, line):
            amt = clean_amount_string(match.group(2) or match.group(3))
            if amt is not None:
                amounts.append(amt)
        return amounts


    def _html_regex_fallback(self, data: str, parse_key: str | None = None) -> float:
        soup = BeautifulSoup(data, "html.parser")
        text = soup.get_text(separator='\n')
        lines = text.split('\n')
        page_total = 0.0
        i = 0
        found_total = False
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if parse_key and parse_key.lower() in line.lower() and not found_total:
                j = i + 1
                print("line-", line, "parse_key->", parse_key)
                while j < len(lines):
                    next_line = lines[j].strip()
                    if next_line:
                        amounts = self._extract_amounts_from_line(next_line, None)
                        page_total += sum(amounts)
                        print("next line-", next_line, "amounts->", amounts)
                        found_total = True
                        break
                    j += 1
                i = j
                if found_total:
                    break
            else:
                amounts = self._extract_amounts_from_line(line, parse_key)
                page_total += sum(amounts)
            i += 1
        return page_total


    def _pdf_page_regex_fallback(self, data: bytes, page_index: int, parse_key: str | None = None) -> float:
        try:
            reader = PyPDF2.PdfReader(BytesIO(data))
            if page_index >= len(reader.pages):
                return 0.0
            text = reader.pages[page_index].extract_text()
            if not text or not text.strip():
                return 0.0
            return sum(
                amt
                for line in text.split('\n')
                if line.strip()
                for amt in self._extract_amounts_from_line(line, parse_key)
            )
        except Exception as e:
            print(f"PyPDF2 fallback error on page {page_index}: {e}")
            return 0.0

    def _pdf_regex_all_pages(self, data: bytes, parse_key: str | None = None) -> float:
        try:
            reader = PyPDF2.PdfReader(BytesIO(data))
            total = 0.0
            for page in reader.pages:
                text = page.extract_text()
                if not text or not text.strip():
                    continue
                total += sum(
                    amt
                    for line in text.split('\n')
                    if line.strip()
                    for amt in self._extract_amounts_from_line(line, parse_key)
                )
            return total
        except Exception as e:
            print(f"PyPDF2 all-pages error: {e}")
            return 0.0

   
    def _parse_pdf(self, data: bytes, parse_key: str | None = None) -> float:
        """PDF → image per page → LayoutLMv3 image mode → regex fallback per page."""
        try:
            images = convert_from_bytes(data, dpi=200)
        except Exception as e:
            print(f"pdf2image failed: {e}, falling back to regex")
            return self._pdf_regex_all_pages(data, parse_key)

        total = 0.0
        for i, image in enumerate(images):
            print(f"PDF page {i+1} → LayoutLMv3 image-mode (category: {parse_key or 'total'})")
            amount = ask_layoutlm_image(image, parse_key)
            if amount is not None:
                print(f"extracted: {amount}")
                total += amount
            else:
                print(f"not confident, falling back to regex")
                total += self._pdf_page_regex_fallback(data, i, parse_key)
        return total

    def _parse_html(self, data: str, parse_key: str | None = None) -> float:
        print(f"HTML → LayoutLMv3 text-mode (category: {parse_key or 'total'})")
        soup = BeautifulSoup(data, "html.parser")
        text = soup.get_text(separator=' ')
        amount = ask_layoutlm_text(text, parse_key)
        if amount is not None:
            print(f"extracted: {amount}")
            return amount
        print("not confident, falling back to regex")
        return self._html_regex_fallback(data, parse_key)


    def parser(self, parse_key: str | None = None) -> dict:
        bill_dict = {}
        for date, data in self.date_data_dict.items():
            bill_dict[date] = 0.0
            try:
                if isinstance(data, bytes):
                    bill_dict[date] = self._parse_pdf(data, parse_key)
                elif isinstance(data, str):
                    bill_dict[date] = self._parse_html(data, parse_key)
            except Exception as e:
                print(f"Error processing {date}: {e}")
        print("bill dict-", bill_dict)
        return bill_dict