from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak, NextPageTemplate, Table, TableStyle, Flowable, KeepTogether
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from pypdf import PdfReader, PdfWriter

ROOT = Path.cwd()
SOURCE = Path(r'C:\Users\miche\Downloads\dungogpueblos_ Capstone (3).pdf')
INSERT = ROOT / 'tmp' / 'pdfs' / 'capstone_red_revision_insert.pdf'
OUTPUT = ROOT / 'output' / 'pdf' / 'DengueWatch_Capstone_Revised_Adviser_Suggestions_Red.pdf'
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
RED = colors.HexColor('#B00020')
LIGHT = colors.HexColor('#F7F1F2')
GRID = colors.HexColor('#C7B7BA')
TEXT = RED

styles = getSampleStyleSheet()
body = ParagraphStyle('RedBody', parent=styles['BodyText'], fontName='Times-Roman', fontSize=10.1, leading=13.1, textColor=TEXT, spaceAfter=6)
small = ParagraphStyle('RedSmall', parent=body, fontSize=8.6, leading=10.5, spaceAfter=4)
h1 = ParagraphStyle('RedH1', parent=styles['Heading1'], fontName='Times-Bold', fontSize=16, leading=19, textColor=RED, spaceAfter=9)
h2 = ParagraphStyle('RedH2', parent=styles['Heading2'], fontName='Times-Bold', fontSize=12.2, leading=15, textColor=RED, spaceBefore=5, spaceAfter=5)
h3 = ParagraphStyle('RedH3', parent=h2, fontSize=10.6, leading=13, spaceBefore=3, spaceAfter=3)
center_title = ParagraphStyle('RedTitle', parent=h1, alignment=TA_CENTER, fontSize=18, leading=22, spaceAfter=12)
cell = ParagraphStyle('RedCell', parent=small, fontSize=8.5, leading=10.2, spaceAfter=0)
cellhead = ParagraphStyle('RedCellHead', parent=cell, fontName='Times-Bold')

def P(s, style=body):
    return Paragraph(s, style)

def bullets(items):
    return [P('&bull;&nbsp; ' + item, body) for item in items]

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(RED)
    canvas.setFont('Times-Bold', 8)
    canvas.drawString(doc.leftMargin, doc.pagesize[1] - 29, 'DENGUEWATCH | ADVISER REVISION INSERT')
    canvas.setFont('Times-Roman', 8)
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 25, f'Revision insert - page {doc.page}')
    canvas.restoreState()

portrait_frame = Frame(52, 42, letter[0]-104, letter[1]-88, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='portrait_frame')
landscape_size = landscape(letter)
landscape_frame = Frame(42, 42, landscape_size[0]-84, landscape_size[1]-88, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='landscape_frame')
doc = BaseDocTemplate(str(INSERT), pagesize=letter, leftMargin=52, rightMargin=52, topMargin=44, bottomMargin=42, title='DengueWatch Adviser Revisions - Red Text Insert', author='DengueWatch Capstone Authors')
doc.addPageTemplates([
    PageTemplate(id='portrait', frames=portrait_frame, pagesize=letter, onPage=on_page),
    PageTemplate(id='landscape', frames=landscape_frame, pagesize=landscape_size, onPage=on_page),
])

story=[]
story += [P('ADVISER-BASED REVISIONS', center_title), P('DengueWatch: An AI-Assisted Predictive Dengue Surveillance and Hotspot Analytics with Geographic Information System', ParagraphStyle('sub', parent=body, alignment=TA_CENTER, fontName='Times-Bold', fontSize=11, leading=14)), Spacer(1,8)]
story += [P('<b>How to apply this insert.</b> These red passages are replacement or supplemental material mapped to the printed page references in the adviser comments. Insert each passage into its corresponding chapter and remove conflicting statements from the original draft. The supplied manuscript is a PDF, so this copy preserves it and appends the red insert pages for placement in an editable manuscript.', body)]
story += [P('1. Define the prediction target and horizon', h1), P('Replace general statements such as “predict possible hotspots” with the following operational definition:', body)]
story += [P('<b>Prediction target.</b> At the end of calendar month t, using only dengue records, weather observations, and other information available by the forecast issue cutoff, DengueWatch estimates the number of recorded dengue cases in calendar month t+1 for each of Iligan City’s 44 barangays. The primary model target is this next-month barangay case count. A barangay is flagged as a potential planning hotspot when its estimated count is at least 6. This is an internal planning threshold, not an official outbreak declaration or a prediction of an individual resident’s health status.', body)]
story += [P('If the current month is still underway, the system may display a provisional estimate based on confirmed records received to date; the issue date and data cutoff must be shown. Actual weather or case information that became available after the issue cutoff must not be used as a predictor. The target is the following month’s observed count, not a risk label derived from the same month’s input count.', body)]
story += [P('2. Use one documented set of risk bands', h1), P('Use these bands consistently for the forecast map, analytics, and alert review. They describe internal planning categories for a predicted barangay-month count; they are not represented as CHO or DOH outbreak classifications unless a cited written guideline is obtained.', body)]
risk_data = [[P('Predicted count per barangay-month',cellhead),P('Display band',cellhead),P('Interpretation',cellhead)],
 [P('0-5',cell),P('Low',cell),P('Below the prototype planning threshold.',cell)],
 [P('6-50',cell),P('Moderate',cell),P('Meets the internal 6-case planning flag.',cell)],
 [P('51-100',cell),P('High',cell),P('Higher planning priority; not a clinical classification.',cell)],
 [P('101 or more',cell),P('Critical',cell),P('Highest planning band; not an outbreak declaration.',cell)],
 [P('Incomplete or unverified report',cell),P('Unavailable',cell),P('Do not convert missing reporting into zero or assign a risk band.',cell)]]
risk_table=Table(risk_data,colWidths=[1.7*inch,1.05*inch,3.0*inch],repeatRows=1)
risk_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),LIGHT),('GRID',(0,0),(-1,-1),0.45,GRID),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
story += [risk_table, P('Apply the same boundary rules to forecast outputs only when describing predictions, and label historical case totals separately from predicted totals. If CHO provides a written official threshold, cite it and update every occurrence consistently.', body), PageBreak()]

story += [P('3. Data feasibility and inventory',h1), P('The current prototype inventory supports a monthly modeling panel. It does not yet establish that every historical month was completely reported or that the researchers have continuing authorization to use CHO records. The following figures describe the workbook-derived prototype inventory and must be reconfirmed with the data custodian before final claims are made.',body)]
inventory = [[P('Inventory item',cellhead),P('Current prototype inventory',cellhead)],
 [P('Source and record unit',cell),P('Workbook-derived individual case line list; each source row represents a case record, not an aggregate count.',cell)],
 [P('Coverage and geography',cell),P('Admission dates from 2020-01-01 through 2026-07-31; official labels for 44 Iligan City barangays.',cell)],
 [P('Source rows and usable rows',cell),P('10,484 source rows; 10,296 have both a valid admission date and a matched official barangay.',cell)],
 [P('Known quality gaps',cell),P('133 rows have a missing/invalid admission date; 55 lack a matched official barangay; 163 potential duplicate matches are retained and flagged because no stable case identifier is available.',cell)],
 [P('Reporting delay and case definition',cell),P('Cannot be calculated from the supplied file: it has an admission date but no received/entered date. The workbook does not state a versioned case definition or consistently establish confirmed versus suspected status.',cell)],
 [P('Monthly modeling panel',cell),P('3,476 rows: 44 barangays across 79 calendar months, January 2020-July 2026. A row with no source records is not proof of zero incidence or complete reporting.',cell)],
 [P('Weather input',cell),P('Cached Open-Meteo values at one Iligan City center point (8.228 N, 124.2452 E), applied citywide: monthly precipitation sum (mm), monthly mean temperature (degrees C), and mean available hourly relative humidity (%). This is not barangay-level weather.',cell)],
 [P('Weather gaps',cell),P('The cached series is missing February-July 2026. Validate the source and coverage against CHO/PAGASA needs before operational use.',cell)]]
inv=Table(inventory,colWidths=[1.65*inch,4.1*inch],repeatRows=1)
inv.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),LIGHT),('GRID',(0,0),(-1,-1),0.4,GRID),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
story += [inv, Spacer(1,6), P('<b>Feasibility gate.</b> Before model claims or operational use, document written CHO authorization, data custodian, permitted fields, secure transfer/storage, refresh schedule, case-definition version, and reporting-completeness procedure. Add received dates and a barangay-month completeness indicator. Confirmed zero requires a complete reporting period explicitly reported as zero; absent records remain missing/unverified.',body)]
story += [P('The current design uses one modeling row per barangay per month because that is the grain supported by the available dates and prototype forecast. A weekly candidate panel may be evaluated later, but its no-record weeks must remain unverified and excluded until weekly completeness is confirmed. The proposed 50 respondents evaluate usability; they are not the training sample and do not establish model-data sufficiency.',body),PageBreak()]

story += [P('4. Chronological validation and leakage controls',h1), P('Replace the random train-test split and repeated tuning against the test set with the following protocol. All barangays from the same calendar month remain together in one temporal partition.',body)]
story += bullets([
 '<b>Training period:</b> February 2020-November 2023. Fit learned preprocessing and the Random Forest pipeline using training data only.',
 '<b>Validation period:</b> December 2023-February 2025. Select features and tune parameters using this period and training data only.',
 '<b>Final test:</b> forecast inputs from March 2025-June 2026, evaluated against target months April 2025-July 2026. Lock this period before model tuning and score it once after all decisions are frozen.',
 'At each forecast origin, use only records and weather information that would have been available at that issue cutoff. Exclude later case reports, later observed weather, and same-period target values from predictors.',
 'Fit imputation, encoding, scaling, feature selection, and other learned preprocessing within the training pipeline. Do not fit these steps on validation or final-test data.',
 'Compare the count model with a persistence baseline that carries forward the most recent observed monthly count. Report MAE and RMSE for the count forecast. If thresholded hotspot classes are separately evaluated, report per-class precision, recall, F1, and a confusion matrix.',
 'Do not repeatedly tune against the final test period. After its one-time evaluation is recorded, a deployment model may be refit on all available history; preserve the locked evaluation results and model version.'
])
story += [P('Current prototype holdout results',h2)]
metric_data=[[P('Measure',cellhead),P('Random Forest',cellhead),P('Persistence baseline',cellhead),P('Interpretation',cellhead)],
 [P('MAE (cases)',cell),P('1.704',cell),P('1.5298',cell),P('Lower is better; Random Forest is 11.4% worse.',cell)],
 [P('RMSE (cases)',cell),P('2.5026',cell),P('2.6541',cell),P('Lower is better; Random Forest is better on this metric.',cell)]]
mt=Table(metric_data,colWidths=[1.05*inch,1.1*inch,1.35*inch,2.25*inch])
mt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),LIGHT),('GRID',(0,0),(-1,-1),0.4,GRID),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
story += [mt,P('The current model does not outperform the persistence baseline on both count metrics. Therefore, describe it as experimental planning support only; usability scores do not establish prediction accuracy, and no public-health action should be based on an unreviewed forecast.',body),P('For time-ordered evaluation, ordinary random cross-validation can train on future observations and evaluate on earlier ones. Use a chronological split such as the documented scikit-learn TimeSeriesSplit approach where appropriate: <link href="https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html" color="#B00020">scikit-learn TimeSeriesSplit documentation</link>.',small),PageBreak()]

story += [P('5. Revised objectives and evaluation',h1),P('Replace the overlapping objectives and any claim that a usability study proves outbreak prevention with these measurable objectives:',body)]
story += bullets([
 'Evaluate the resident community-report and health-worker dengue-report workflows using task completion, data-entry errors, and time to complete defined scenarios. These measures describe prototype workflow performance; they do not by themselves prove reduced reporting delays in routine CHO operations.',
 'Evaluate one-calendar-month-ahead barangay case-count forecasts against later observations using the chronological holdout and persistence baseline. Report MAE and RMSE; add classification measures only if the binary or multi-class risk output is separately evaluated.',
 'Verify mapping, case-review, and alert functions using defined functional scenarios, including CHO review before a public risk alert is issued. Do not describe a model forecast as a confirmed dengue case or outbreak.',
 'Evaluate usability through task performance and correctly scored SUS. Measure increased awareness only if a separate pre/post awareness instrument is added. Treat reduced outbreaks as a possible longer-term benefit, not an outcome established by this prototype evaluation.'
])
story += [P('Correct System Usability Scale procedure',h2),P('Administer the standard ten-item SUS using five response options. For each odd-numbered item (1, 3, 5, 7, 9), subtract 1 from the response. For each even-numbered item (2, 4, 6, 8, 10), subtract the response from 5. Sum the ten contributions and multiply by 2.5 to obtain a score from 0 to 100. Do not calculate SUS as the average of 1-5 responses or apply custom acceptability bands to SUS. Analyze a locally written functionality or acceptability questionnaire separately, label it as custom, and report its own scale.',body)]
story += [P('Attach the actual questionnaire and task scenarios in the appendices. Record task completion, errors, and elapsed time separately from SUS.',body),P('Consistent purposive usability sample (50 participants)',h2)]
sample_data=[[P('Participant group',cellhead),P('n',cellhead),P('Purpose',cellhead)],
 [P('CHO staff',cell),P('5',cell),P('Review, monitoring, and approval workflows.',cell)],
 [P('CHW',cell),P('5',cell),P('Suspected-case submission and follow-up.',cell)],
 [P('BHW',cell),P('10',cell),P('Barangay-level case and field workflows.',cell)],
 [P('LGU representatives',cell),P('5',cell),P('Planning maps, reports, and analytics.',cell)],
 [P('Residents',cell),P('25',cell),P('Mobile alerts, hotspot map, and community reporting.',cell)],
 [P('Total',cell),P('50',cell),P('Usability sample only; not a model-training or accuracy sample.',cell)]]
st=Table(sample_data,colWidths=[1.55*inch,.5*inch,3.7*inch],repeatRows=1)
st.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),LIGHT),('GRID',(0,0),(-1,-1),0.4,GRID),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
story += [st,PageBreak()]

story += [P('6. Align the data dictionary and technical architecture',h1),P('Describe the prototype that is actually configured. The development system uses Django and its ORM with SQLite. Do not describe Cloud Firestore as the primary store for relational case records unless it is selected and configured for the deployed system. A production database choice should be stated only after it is confirmed.',body),P('Apply these corrections throughout the architecture, ERD, and data dictionary:',h2)]
story += bullets([
 '<b>Barangay and Purok:</b> use integer primary keys and matching integer foreign keys. Purok stores barangay_id as a foreign key; do not define the relationship only by a barangay name.',
 '<b>DengueCase:</b> one row represents one individual case record. Store aggregated counts in a separate barangay-month table or derived dataset, not as an unrestricted case_count on each individual row.',
 '<b>Diagnosis and outcome:</b> keep suspected/confirmed diagnostic classification separate from outcomes such as recovered/deceased.',
 '<b>CommunityReport:</b> resident environmental observations have a separate entity and review workflow. They are not dengue cases and do not enter case-count targets unless CHO verifies and records a case through the proper workflow.',
 '<b>HotspotPrediction:</b> define each field once and store barangay_id, forecast issue timestamp, input cutoff, target month, predicted count, derived display band, and model version. Remove repeated risk_level and analysis_remarks entries.',
 '<b>User passwords:</b> store only Django’s securely hashed password representation; do not describe passwords as recoverably encrypted.'
])
story += [P('The prediction is reproducible only when its forecast issue date, exact input cutoff, target period, and model version are retained. Public maps should display aggregated barangay-level results. Identifiable case records remain restricted to authorized health personnel through role-based access. Document CHO-approved retention, secure deletion, access logging, and incident procedures before production use.',body),PageBreak()]

story += [P('7. Privacy, feature justification, and CHO review',h1),P('Keep resident environmental observations separate from verified dengue case records. Require CHO review before a forecast-based alert is published to residents. A forecast is planning support, not an outbreak declaration or clinical assessment.',body),P('Age, sex, and blood type originate as patient-level attributes and must not be presented as individual risk factors. The initial forecast should omit blood type unless its availability and lawful use are confirmed and a feature-ablation comparison demonstrates value on the same untouched final test period. If it is retained only for exploratory analysis, use de-identified, lagged barangay-month aggregates and never expose individual values in forecast outputs.',body),P('Document how patient-level source records are transformed into aggregate barangay-month features, who can access identifiers, what is removed or retained, and how long data are held. The public-facing map must not expose names, addresses, or other patient identifiers.',body),P('8. Statistical, reference, and sample-count audit',h1),P('The following corrections are needed before submission. They are written conservatively because the supplied PDFs do not include the source documents needed to verify every citation:',body)]
story += bullets([
 'On printed page 3, delete the comparison that labels a change from 338,983 to 62,313 as a 73% increase. Those displayed values do not support that direction or percentage. Restore a comparison only after confirming the same geographic scope, date window, and source table, then show the calculation.',
 'On printed page 20, reconcile the Acharjee et al. (2022) attribution with reference [32], which lists Sarma et al. (2020). Until the source and description are matched, remove or rewrite the paragraph; do not invent bibliographic details.',
 'On printed page 22, verify that the neural-network review description matches the title and authors listed in reference [35]. Remove or rewrite it until confirmed.',
 'On printed page 12, define DengueWatch as the prototype developed in this study. Do not cite a general dengue-information page as the source of the project’s own name.',
 'Use one respondent allocation everywhere: 5 CHO, 5 CHW, 10 BHW, 5 LGU representatives, and 25 residents (50 total). Clearly identify it as a purposive usability sample.'
])
story += [P('A complete claim-by-claim audit of all remaining citations requires checking each cited publication or official source. Confirm the author, title, year, URL/DOI, and in-text citation number against the source itself before stating that the audit is complete. The supplied files do not establish CHO data authorization or an approved retention schedule; describe both as pending until supporting records are available.',body),PageBreak()]

story += [P('9. Editorial and figure corrections',h1),P('Before final submission, complete the following consistency pass across the manuscript:',body)]
story += bullets([
 'Replace the sideways or cropped data-flow diagram with the landscape diagram on the following insert page; enlarge text in the architecture and ERD.',
 'Use sequential figure and table numbers, then update every cross-reference in the text. Remove repeated methodology paragraphs and duplicated field definitions.',
 'Correct “AI-Asssited” to “AI-Assisted” and “breed more faster” to “breed more rapidly.”',
 'Use future tense for planned procedures and past tense only for work already completed. Recheck page breaks and table layouts after replacing diagrams and revising appendices.',
 'Use the following replacement workflow and conceptual ERD only after reconciling table and key names with the final Django models.'
])
story += [P('The pages that follow are replacement diagrams for the system workflow and core data relationships. Keep the diagram labels red as revised content; borders and connectors are visual guides.',body),NextPageTemplate('landscape'),PageBreak()]

class Diagram(Flowable):
    def __init__(self, kind, width, height):
        super().__init__(); self.kind=kind; self.width=width; self.height=height
    def box(self,c,x,y,w,h,title,lines,fs=8.5):
        c.setStrokeColor(GRID); c.setFillColor(colors.white); c.roundRect(x,y,w,h,7,stroke=1,fill=1)
        c.setFillColor(RED); c.setFont('Times-Bold',fs+1); c.drawCentredString(x+w/2,y+h-15,title)
        c.setFont('Times-Roman',fs)
        yy=y+h-29
        for line in lines:
            c.drawCentredString(x+w/2,yy,line); yy-=11
    def arrow(self,c,x1,y1,x2,y2):
        c.setStrokeColor(GRID); c.setFillColor(GRID); c.setLineWidth(1.2); c.line(x1,y1,x2,y2)
        import math
        a=math.atan2(y2-y1,x2-x1); L=6
        p1=(x2-L*math.cos(a-0.45),y2-L*math.sin(a-0.45)); p2=(x2-L*math.cos(a+0.45),y2-L*math.sin(a+0.45))
        path=c.beginPath(); path.moveTo(x2,y2); path.lineTo(*p1); path.lineTo(*p2); path.close()
        c.drawPath(path,stroke=0,fill=1)
    def draw(self):
        c=self.canv; c.setFillColor(RED)
        if self.kind=='workflow':
            W=self.width
            # main sequence
            boxes=[(8,300,133,108,'CHO case records',['Line-list records','Case definition + dates']),
                   (165,300,133,108,'Weather + places',['Open-Meteo monthly','Official barangay locations']),
                   (322,300,133,108,'Data quality gate',['Valid date + barangay','Duplicates flagged','Completeness retained']),
                   (479,300,133,108,'Monthly panel',['44 barangays x month','Count + completeness','Missing is not zero']),
                   (636,300,110,108,'Forecast',['One month ahead','Random Forest','Version + cutoff'])]
            for b in boxes:self.box(c,*b[:5],b[5],7.5)
            for x in [141,298,455,612]:self.arrow(c,x,354,x+20,354)
            self.box(c,498,115,205,105,'CHO review and publication',['Review forecast and area evidence','Approve before resident alert','Planning support, not outbreak declaration'],8)
            self.box(c,264,115,190,105,'Chronological evaluation',['Earlier months: train / validation','Later months: untouched test','Compare with persistence; MAE / RMSE'],8)
            self.box(c,25,115,190,105,'Access and privacy',['Role-limited case details','Aggregated public map','Resident reports kept separate'],8)
            self.arrow(c,690,300,620,220); self.arrow(c,498,168,454,168); self.arrow(c,264,168,215,168)
        else:
            self.box(c,8,300,145,105,'UserAccount',['user_id (PK)','role; contact','password hash','assigned barangay/purok'],7.6)
            self.box(c,281,300,145,105,'Barangay',['barangay_id (PK)','official name + geometry'],7.6)
            self.box(c,554,300,145,105,'Purok',['purok_id (PK)','barangay_id (FK)','purok name'],7.6)
            self.box(c,8,140,145,112,'DengueCase',['case_id (PK)','barangay_id / purok_id (FK)','case dates + definition','diagnosis separate from outcome'],7.2)
            self.box(c,281,140,145,112,'CommunityReport',['report_id (PK)','resident_id + location (FK)','observation + review status','not a case-count target'],7.2)
            self.box(c,554,140,145,112,'WeatherMonth',['weather_id (PK)','month + source / units','matched geography','retrieval date'],7.4)
            self.box(c,140,8,190,98,'BarangayMonth',['barangay_id (FK) + month','case count + completeness','lagged predictors'],7.5)
            self.box(c,380,8,190,98,'HotspotPrediction',['prediction_id (PK)','issue date + input cutoff','target month + model version','count + display band'],7.5)
            self.arrow(c,281,345,153,345); self.arrow(c,554,345,426,345)
            self.arrow(c,80,300,80,252); self.arrow(c,353,300,353,252); self.arrow(c,626,300,626,252)
            self.arrow(c,153,175,215,106); self.arrow(c,353,140,250,106); self.arrow(c,626,140,300,106)
            self.arrow(c,330,55,380,55)
            c.setFont('Times-Roman',7.5); c.setFillColor(RED); c.drawCentredString(self.width/2, 0,'Use integer foreign keys consistently. Keep incomplete reporting unavailable, not zero.')

diag_w,diag_h=landscape_size[0]-84,430
story += [P('Figure: revised system data flow',h2),P('One barangay-month row; forecast the next calendar month using information available at issue time.',small),Diagram('workflow',diag_w,diag_h),PageBreak(),P('Figure: revised conceptual entity relationships (ERD)',h2),Diagram('erd',diag_w,diag_h)]
doc.build(story)

# Preserve every original page and append the red replacement insert pages.
source_reader=PdfReader(str(SOURCE)); insert_reader=PdfReader(str(INSERT)); writer=PdfWriter()
for page in source_reader.pages: writer.add_page(page)
for page in insert_reader.pages: writer.add_page(page)
with OUTPUT.open('wb') as stream: writer.write(stream)
print(f'created {OUTPUT} with {len(source_reader.pages)} original pages + {len(insert_reader.pages)} red revision pages')
