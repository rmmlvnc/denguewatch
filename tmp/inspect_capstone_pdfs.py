from pypdf import PdfReader
from pathlib import Path
paths = [Path(r'C:\Users\miche\Downloads\Capstone Suggestions.pdf'), Path(r'C:\Users\miche\Downloads\dungogpueblos_ Capstone (4).pdf')]
for path in paths:
    reader = PdfReader(path)
    print(f'\nFILE {path.name} PAGES {len(reader.pages)}')
    for index, page in enumerate(reader.pages):
        text = (page.extract_text() or '').replace('\n', ' ')
        print(f'PAGE {index + 1}: {text[:1100]}')
