import re
from io import BytesIO
from bs4 import BeautifulSoup
from pdf2image import convert_from_bytes
import pdfplumber
from date_op import date_in_range, parse_date
from layoutmlv3_model import LayoutModel


_CONFIDENCE_THRESHOLD = 0.5
_TOTAL_QUESTIONS = [
"What is the total amount to pay?",
"What is the total amount due?",
"What is the grand total?",
"What is the final total?",
"What is the amount?"]
_CATEGORY_QUESTION_TEMPLATES = [
    "What is the amount paid for {category}?",
    "How much is the {category} charge?",
    "What is the {category} fee?",
    "What is the cost of {category}?"]
_DATE_QUESTIONS = [
    "What is the invoice date in format of mm/yy?",
    "What date is this invoice for?",
    "What month is this receipt for?"]


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
    def __init__(self, date_data_dict: dict, currency_symbols, range: list[str], parse_key: str | None = None):
        self.date_data_dict = date_data_dict        
        self.currency_symbols = currency_symbols
        self.parse_key = parse_key
        self.range = range
        self.ML_model = LayoutModel(parse_key=parse_key, threshold=_CONFIDENCE_THRESHOLD, questions= _CATEGORY_QUESTION_TEMPLATES if parse_key else _TOTAL_QUESTIONS, date_questions=_DATE_QUESTIONS)

    
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
        print(f"Extracted amounts from line '{line}': {amounts}")
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


    def _pdf_page_regex_fallback(self, data: bytes, parse_key: str | None = None) -> float:
        try:
            reader = pdfplumber.open(BytesIO(data))
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
            print(f"PyPDF2 fallback error: {e}")
            return 0.0
        
    def _html2text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator='\n')
    
    def _pdf2text(self, pdf_bytes: bytes, i: int) -> str:
        reader = pdfplumber.open(BytesIO(pdf_bytes))
        return reader.pages[i].extract_text() if i < len(reader.pages) else ""

    def _get_amount_from_text(self, text: str) ->float:
        amounts, dates = self.ML_model.ask_layoutlm_text(text)
        best_amount = None
        best_score = 0.0
        for answer, score in amounts:
            if score > _CONFIDENCE_THRESHOLD and score > best_score:
                amount = extract_amount_from_answer(answer)
                if amount is not None:
                    best_amount = amount
                    best_score = score
        best_date = None
        best_date_score = 0.0   
        for answer, score in dates:
            if score > _CONFIDENCE_THRESHOLD and score > best_date_score:
                best_date = answer
                best_date_score = score 
        return best_amount, best_date
            
    def _parse_pdf(self, data: bytes, parse_key: str | None = None, progress_cb=None):
        """PDF → text → LayoutLMv3 text mode → regex fallback per page."""
        try:
            images = convert_from_bytes(data, dpi=200)
        except Exception as e:
            print(f"pdf2image failed: {e}, falling back to regex")
            return self._pdf_page_regex_fallback(data, parse_key)
        total = 0.0
        best_date = None
        for i in range(len(images)):
            print(f"PDF page {i+1} → LayoutLMv3 text-mode (category: {parse_key or 'total'})")
            text = self._pdf2text(data, i)
            print(f"Extracted text from PDF page {i+1}:\n{text}")
            if progress_cb:
                progress_cb(step="model",
                            message=f"AI model on PDF page {i+1}/{len(images)}",
                            detail=text[:60].strip())
            best_amount, best_date = self._get_amount_from_text(text)
            best_date = parse_date(best_date)
            if best_amount is not None:
                print(f"extracted: {best_amount}")
                total += best_amount
            else:
                if progress_cb:
                    progress_cb(step="regex",
                                message=f"AI not confident on page {i+1}, using regex",
                                detail="")
                print(f"not confident, falling back to regex")
                total += self._pdf_page_regex_fallback(data, parse_key)
        return total, best_date

    def _parse_html(self, data: str, parse_key: str | None = None, progress_cb=None):
        print(f"HTML → LayoutLMv3 text-mode (category: {parse_key or 'total'})")
        if progress_cb:
            progress_cb(step="model",
                        message="Running AI model on HTML invoice",
                        detail="")
        text = self._html2text(data)
        best_amount, best_date = self._get_amount_from_text(text)
        best_date = parse_date(best_date)
        if best_amount is not None:
            print(f"extracted: {best_amount}")
            return best_amount, best_date
        if progress_cb:
            progress_cb(step="regex",
                        message="AI not confident, using regex fallback",
                        detail="")
        print("not confident, falling back to regex")
        return self._html_regex_fallback(data, parse_key), best_date


    def parser(self, progress_cb=None) -> dict:
        bill_dict = {}
        total_invoices = sum(len(v) for v in self.date_data_dict.values())
        processed = 0
        for date, data_list in self.date_data_dict.items():
            for data in data_list:
                processed += 1
                try:
                    if isinstance(data, bytes):
                        if progress_cb:
                            progress_cb(step="extract",
                                        message=f"Processing invoice {processed}/{total_invoices}",
                                        detail=date)
                        current_total, extracted_date = self._parse_pdf(data, self.parse_key)
                        print(f"Processed PDF for date {date}, current total: {current_total}, extracted date: {extracted_date}")
                        print(f"Date range: {self.range[0]} to {self.range[1]}")
                        if extracted_date is not None and date_in_range(extracted_date, self.range[0], self.range[1]):
                            bill_dict[extracted_date] = bill_dict.get(extracted_date, 0.0) + current_total
                        else:
                            bill_dict[date] = bill_dict.get(date, 0.0) + current_total
                        print(f"Processed PDF for date {date}, current total: {bill_dict[date]}")
                    elif isinstance(data, str):
                        if progress_cb:
                            progress_cb(step="extract",
                                        message=f"Processing invoice {processed}/{total_invoices}",
                                        detail=date)
                        current_total, extracted_date = self._parse_html(data, self.parse_key)
                        if extracted_date is not None and date_in_range(extracted_date, self.range[0], self.range[1]):
                            bill_dict[extracted_date] = bill_dict.get(extracted_date, 0.0) + current_total
                        else:
                            bill_dict[date] = bill_dict.get(date, 0.0) + current_total
                except Exception as e:
                    print(f"Error processing {date}: {e}")
        print("bill dict-", bill_dict)
        return bill_dict