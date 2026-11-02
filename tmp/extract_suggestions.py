from pypdf import PdfReader
from pathlib import Path
reader=PdfReader(r'C:\Users\miche\Downloads\Capstone Suggestions.pdf')
for i,page in enumerate(reader.pages):
    print(f'===== ADVISER PAGE {i+1} =====')
    print(page.extract_text() or '')
