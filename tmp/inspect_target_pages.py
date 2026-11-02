from pypdf import PdfReader
from pathlib import Path
r=PdfReader(r'C:\Users\miche\Downloads\dungogpueblos_ Capstone (4).pdf')
selected={3,7,8,12,20,22,29,30,31,32,34,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,68,69,70,71,72,73,74,75}
for i,p in enumerate(r.pages,1):
    if i in selected:
        text=(p.extract_text() or '').replace('\n',' ')
        print(f'===== PAPER PAGE {i} =====\n{text[:1650]}\n')
