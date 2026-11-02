from pypdf import PdfReader
r=PdfReader(r'C:\Users\miche\Downloads\dungogpueblos_ Capstone (4).pdf')
for i in [75,76,77,78]:
 print(f'===== PAGE {i+1} =====')
 print(r.pages[i].extract_text() or '')
