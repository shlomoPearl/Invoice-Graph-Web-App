import re
import PyPDF2
from io import BytesIO
from bs4 import BeautifulSoup


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


class ReadBill:
    def __init__(self, date_data_dict: dict, currency_symbols):
        self.date_data_dict = date_data_dict
        self.currency_symbols = currency_symbols

    def extract_amounts_from_line(self, line, parse_key=None):
        amounts = []
        if parse_key and parse_key.lower() not in line.lower():
            return amounts

        # Build regex for all currency symbols
        currency_pattern = '|'.join(re.escape(sym) for sym in self.currency_symbols)
        # Match patterns like '₪3.90', '3.90₪', with or without spaces
        pattern = rf'({currency_pattern})\s*([\d,]+\.\d+|\d+)|([\d,]+\.\d+|\d+)\s*({currency_pattern})'

        for match in re.finditer(pattern, line):
            # Try both currency before and after
            if match.group(2):  # currency before
                amt = clean_amount_string(match.group(2))
            elif match.group(3):  # currency after
                amt = clean_amount_string(match.group(3))
            else:
                amt = None
            if amt is not None:
                amounts.append(amt)
        return amounts

    def parser(self, parse_key=None):
        bill_dict = {}
        for date, data in self.date_data_dict.items():
            bill_dict[date] = 0.0
            try:
                # Detect PDF (bytes) or HTML (str)
                if isinstance(data, bytes):
                    pdf_data = BytesIO(data)
                    if not pdf_data.getvalue():
                        continue
                    pdf_file = PyPDF2.PdfReader(pdf_data)
                    if len(pdf_file.pages) == 0:
                        continue
                    for page in pdf_file.pages:
                        try:
                            text = page.extract_text()
                            if not text or not text.strip():
                                continue
                            lines = text.split('\n')
                            page_total = 0.0
                            for line in lines:
                                if line.strip():
                                    amounts = self.extract_amounts_from_line(line, parse_key)
                                    page_total += sum(amounts)
                            bill_dict[date] += page_total
                        except Exception as e:
                            print(f"Error processing {date}: {e}")
                elif isinstance(data, str):
                    print("HTML")
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
                            # Look for amount in the next non-empty line
                            j = i + 1
                            print("line-", line, "parse_key->", parse_key)
                            while j < len(lines):
                                next_line = lines[j].strip()
                                if next_line:
                                    amounts = self.extract_amounts_from_line(next_line, None)
                                    page_total += sum(amounts)
                                    print("next line-", next_line, "amounts->", amounts)
                                    found_total = True
                                    break
                                j += 1
                            i = j  # Skip to the line after the amount
                            if found_total:
                                break  # Stop after first TOTAL
                        else:
                            amounts = self.extract_amounts_from_line(line, parse_key)
                            page_total += sum(amounts)
                        i += 1
                    bill_dict[date] += page_total
            except Exception as e:
                print(f"Error processing {date}: {e}")
        print("bill dict-", bill_dict)
        return bill_dict
