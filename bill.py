import re
import PyPDF2
from io import BytesIO
from bs4 import BeautifulSoup
from pdf2image import convert_from_bytes
from layoutmlv3_model import LayoutModel


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


class ReadBill:
    def __init__(self, date_data_dict: dict, currency_symbols, parse_key: str | None = None):
        self.date_data_dict = date_data_dict
        self.currency_symbols = currency_symbols
        self.parse_key = parse_key
        self.ML_model = LayoutModel(parse_key=parse_key, threshold=_CONFIDENCE_THRESHOLD, questions= _CATEGORY_QUESTION_TEMPLATES if parse_key else _TOTAL_QUESTIONS)

    
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
            amounts = self.ML_model.ask_layoutlm_image(image)
            best_amount = None
            best_score = 0.0
            for answer, score in amounts:
                if score > _CONFIDENCE_THRESHOLD and score > best_score:
                    amount = extract_amount_from_answer(answer)
                    if amount is not None:
                        best_amount = amount
                        best_score = score
            if best_amount is not None:
                print(f"extracted: {best_amount}")
                total += best_amount
            else:
                print(f"not confident, falling back to regex")
                total += self._pdf_page_regex_fallback(data, i, parse_key)
        return total

    def _parse_html(self, data: str, parse_key: str | None = None) -> float:
        print(f"HTML → LayoutLMv3 text-mode (category: {parse_key or 'total'})")
        soup = BeautifulSoup(data, "html.parser")
        text = soup.get_text(separator=' ')
        amounts = self.ML_model.ask_layoutlm_text(text)
        best_amount = None
        best_score = 0.0
        for answer, score in amounts:
            if score > _CONFIDENCE_THRESHOLD and score > best_score:
                amount = extract_amount_from_answer(answer)
                if amount is not None:
                    best_amount = amount
                    best_score = score
        if best_amount is not None:
            print(f"extracted: {best_amount}")
            return best_amount
        print("not confident, falling back to regex")
        return self._html_regex_fallback(data, parse_key)


    def parser(self) -> dict:
        bill_dict = {}
        for date, data in self.date_data_dict.items():
            try:
                if isinstance(data, bytes):
                    bill_dict[date] = bill_dict[date].get(date, 0.0) + self._parse_pdf(data, self.parse_key)
                elif isinstance(data, str):
                    bill_dict[date] = bill_dict.get(date, 0.0) + self._parse_html(data, self.parse_key)
            except Exception as e:
                print(f"Error processing {date}: {e}")
        print("bill dict-", bill_dict)
        return bill_dict