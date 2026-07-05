from __future__ import print_function
import base64
from datetime import datetime
from googleapiclient.errors import HttpError
from sqlalchemy.util import defaultdict


# Convert date from dd/mm/yyyy format to yyyy/mm/dd format with month +1
def increment_date(date_str):
    date_obj = datetime.strptime(date_str, '%d/%m/%Y')
    month = date_obj.month + 1
    year = date_obj.year
    day = date_obj.day
    if month > 12:
        month = 1
        year += 1
    return f"{year:04d}/{month:02d}/{day:02d}"


# Extract date from list format and return as mm/yyyy with month -1
def decrement_date(date_list):
    month_name = date_list[2]
    year = date_list[3]
    month_dict = {
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
    }
    month_num = month_dict[month_name] - 1
    year_num = int(year)
    if month_num < 1:
        month_num = 12
        year_num -= 1
    return f"{month_num:02d}/{year_num}"


class Gmail:
    def __init__(self, address, subject, result_num=36, date_range=[]):
        self.address = address
        self.subject = subject
        self.result_num = result_num
        self.date_range = date_range

    def search_mail(self, service):
        query_parts = [f"from:{self.address}"]
        if self.subject:
            query_parts.append(f"subject:{self.subject}")
        query_parts.append(f"after:{increment_date(self.date_range[0])}")
        query_parts.append(f"before:{increment_date(self.date_range[1])}")
        query = " ".join(query_parts)
        print(f"Query: {query}")
        try:
            results = service.users().messages().list(userId="me", maxResults=self.result_num, q=query).execute()
            date_attachment_dict = defaultdict(list)
            for message in results.get('messages', []):
                msg = service.users().messages().get(userId='me', id=message['id']).execute()
                date = None
                for header in msg['payload']['headers']:
                    if header['name'] == 'Date':
                        date_time_list = header['value'].split(' ')
                        date = decrement_date(date_time_list)
                        break
                found_pdf = False
                data = None
                if 'parts' in msg['payload']:
                    for part in msg['payload']['parts']:
                        if part.get('filename', '').endswith('.pdf'):
                            attachment_data = part['body']['attachmentId']
                            attachment = service.users().messages().attachments() \
                                .get(userId='me', messageId=message['id'], id=attachment_data).execute()
                            data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                            found_pdf = True
                            break
                if not found_pdf:
                    # Look for 'text/html' part
                    html_data = None
                    if 'parts' in msg['payload']:
                        for part in msg['payload']['parts']:
                            if part.get('mimeType') == 'text/html':
                                html_data = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                                break
                    else:
                        if msg['payload'].get('mimeType') == 'text/html':
                            data = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8')
                if data and date in date_attachment_dict:
                    date_attachment_dict[date].append(data)
                elif data:
                    date_attachment_dict[date] = [data]
            print(f"Length of Date-Attachment Dict: {len(date_attachment_dict)}")
            return date_attachment_dict
        except HttpError as error:
            print(f"An error occurred: {error}")
