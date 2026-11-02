from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, KeepTogether,
)


ROOT = Path.cwd()
SOURCE = Path(r"C:\Users\miche\Downloads\dungogpueblos_ Capstone (4).pdf")
OUT_DIR = ROOT / "output" / "pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)
INSERT = ROOT / "tmp" / "current_system_replacement_pages.pdf"
OUTPUT = OUT_DIR / "DengueWatch_Capstone_Updated_Current_System_Red.pdf"

RED = colors.HexColor("#C00000")
PALE = colors.HexColor("#FFF3F3")
RULE = colors.HexColor("#D99A9A")

sample = getSampleStyleSheet()
title = ParagraphStyle(
    "RedTitle", parent=sample["Title"], fontName="Helvetica-Bold",
    fontSize=19, leading=23, textColor=RED, alignment=TA_CENTER,
    spaceAfter=12,
)
sub = ParagraphStyle(
    "RedSubtitle", parent=sample["BodyText"], fontName="Helvetica-Bold",
    fontSize=10.5, leading=14, textColor=RED, alignment=TA_CENTER,
    spaceAfter=12,
)
h1 = ParagraphStyle(
    "RedH1", parent=sample["Heading1"], fontName="Helvetica-Bold",
    fontSize=15, leading=18, textColor=RED, spaceBefore=5, spaceAfter=8,
)
h2 = ParagraphStyle(
    "RedH2", parent=sample["Heading2"], fontName="Helvetica-Bold",
    fontSize=11.5, leading=14, textColor=RED, spaceBefore=4, spaceAfter=5,
)
body = ParagraphStyle(
    "RedBody", parent=sample["BodyText"], fontName="Helvetica",
    fontSize=9.4, leading=13, textColor=RED, spaceAfter=6,
)
small = ParagraphStyle(
    "RedSmall", parent=body, fontSize=8.1, leading=10.2, spaceAfter=3,
)
bullet = ParagraphStyle(
    "RedBullet", parent=body, leftIndent=14, firstLineIndent=-8,
    spaceAfter=4,
)
th = ParagraphStyle("RedTH", parent=small, fontName="Helvetica-Bold")
td = ParagraphStyle("RedTD", parent=small)
tdcenter = ParagraphStyle("RedTDCenter", parent=td, alignment=TA_CENTER)


def P(text, style=body):
    return Paragraph(text, style)


def bullets(items):
    return [P("&#8226;&nbsp; " + item, bullet) for item in items]


def table(rows, widths, repeat=1, center_cols=()):
    data = []
    for ri, row in enumerate(rows):
        row_style = th if ri == 0 else td
        data.append([
            P(str(value), (th if ri == 0 else (tdcenter if ci in center_cols else row_style)))
            for ci, value in enumerate(row)
        ])
    result = Table(data, colWidths=widths, repeatRows=repeat, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return result


def page_chrome(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(RED)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(doc.leftMargin, doc.pagesize[1] - 25, "DENGUEWATCH | CURRENT-SYSTEM REVISION")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 23, f"Red replacement text | {doc.page}")
    canvas.restoreState()


frame = Frame(52, 42, letter[0] - 104, letter[1] - 78,
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
              id="main")
doc = BaseDocTemplate(
    str(INSERT), pagesize=letter, leftMargin=52, rightMargin=52,
    topMargin=42, bottomMargin=42,
    title="DengueWatch capstone current system revisions",
    author="DengueWatch capstone authors",
)
doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page_chrome)])
story = []

story += [
    P("DENGUEWATCH CAPSTONE REVISIONS", title),
    P("Replacement sections aligned with the current system and adviser suggestions", sub),
    P("How to use this copy. The submitted manuscript was provided as a PDF, so these red pages are replacement text appended to a copy of the original 79-page paper. Insert each section at the printed page noted below and remove the conflicting draft wording. The Capstone Suggestions PDF is reviewer guidance, not part of the research paper, so it is not edited here.", body),
    P("The system’s current saved evaluation reports 85.16% hotspot precision. This value is included as measured, together with recall, F1, count errors, baselines, and the test-period limitation. It must not be described as proof that the model is ready for public-health operations.", body),
    P("Replacement map", h2),
    table([
        ["Replace or add at printed pages", "Sections in this insert"],
        ["7–9", "Objectives, scope, forecast target and limits"],
        ["32–33; 42–49", "Data feasibility, risk rules, training and validation"],
        ["50–63; 65", "Forecast record, data model, and current software architecture"],
        ["66–73", "Model results, usability method, and SUS scoring"],
    ], [2.1 * inch, 4.1 * inch]),
    PageBreak(),
]

story += [P("Chapter 1 replacement text", h1), P("Printed pages 7–9: objectives, scope, and limitations", small)]
story += [
    P("<b>Objective of the study.</b> This study develops and evaluates DengueWatch, a system for dengue case reporting, historical mapping, and monthly forecasting in Iligan City. The study will:", body),
    *bullets([
        "Provide digital tools for authorized staff to record, review, and monitor dengue case information; assess the reporting workflow using task completion, entry errors, and completion time.",
        "Estimate the next calendar month’s recorded dengue case count for each of Iligan City’s 44 barangays using a Random Forest regression model; compare its results with simple count baselines on later months.",
        "Check historical maps, forecast displays, case review, and CHO alert approval using defined system scenarios.",
        "Assess usability through task results and a correctly scored ten-item System Usability Scale (SUS). Analyze any locally written feedback survey separately.",
    ]),
    P("<b>Forecast scope.</b> At an issue cutoff in month t, the system estimates the number of recorded dengue case records for month t+1 in each barangay. The prediction unit is one barangay-month and the forecast horizon is one calendar month. It predicts a count; a hotspot flag is a separate rule applied to the predicted count. It does not diagnose a person or declare an outbreak.", body),
    P("<b>Current hotspot rules.</b> For model evaluation, an observed hotspot is a barangay-month with at least 2 actual recorded cases. The system flags a forecast for planning review when the predicted next-month count is at least 3. These are internal study cutoffs, not official DOH or CHO outbreak definitions. Keep this distinction separate from the historical-map display bands: 0 recorded cases, Low 1–5, Moderate 6–50, High 51–100, and Critical 101 or more. Historical bands describe selected historical counts; they are not forecast probabilities.", body),
    P("<b>Limitations.</b> The active source is an individual case line list. The project team identifies the source as CHO-verified, but the workbook does not provide a versioned case definition, received/report date, or stable de-identified case key. Therefore, results refer to recorded case counts, and reporting delay or unique-person counts cannot be calculated from this file. Empty barangay-month cells were treated as zero based on the project team’s completeness confirmation; a separate CHO zero-report register was not supplied. Forecasts are planning support and require health-personnel review before action or public release.", body),
    P("The study does not claim that the system prevents outbreaks. A usability sample can evaluate whether participants can use the system; it cannot establish prediction accuracy or a reduction in dengue incidence.", body),
    PageBreak(),
]

story += [P("Chapter 3 replacement text", h1), P("Printed pages 32–33: current data-feasibility inventory", small)]
story += [table([
    ["Inventory item", "Current system/source information", "Limitation or required record"],
    ["Active source", "DENGUE DATASETS 2018_2026 - CHO Dengue Records.csv, consolidated as WILBUR_DSO_dengue_2018_2026_authoritative.csv.", "The research team reports that the uploaded source was verified by CHO. Keep written access approval and permitted-use details with the project records."],
    ["Coverage and source unit", "14,118 individual case-line records; valid admission-date range 2018-01-01 to 2026-07-31; 44 official Iligan barangays.", "These are source records, not independently verified unique people. The file does not include a received/report-entry date."],
    ["Usable source records", "14,084 rows have a valid admission date and an official Iligan barangay match for spatial and time aggregation.", "Rows outside this usable subset remain in the retained source and are flagged; they are not silently deleted."],
    ["Quality flags", "45 records have one or more missing requested fields; 101 extra exact-repeat rows are flagged; 36 Year/admission-date disagreements; 31 records lack an official Iligan barangay match; 8 name a city outside Iligan.", "Flags can overlap. No stable case ID is supplied, so potential duplicates require CHO review. Two rows have missing/invalid admission dates."],
    ["Monthly modeling panel", "4,532 barangay-month rows (44 barangays × 103 months, Jan 2018–Jul 2026); 4,444 rows are usable for the saved model after feature/target preparation.", "The model’s row is one barangay and one calendar month, not one patient."],
    ["Zero months", "1,398 empty cells were encoded as zero under the project team’s completeness confirmation.", "No separate CHO zero-report register is available to independently distinguish all true zeros from missing reports."],
    ["Weather", "Cached Open-Meteo historical estimates: monthly precipitation sum (mm), monthly mean temperature (°C), and monthly mean relative humidity (%). One boundary-derived representative point per barangay; 44 requested points returned 8 distinct grid cells.", "Weather is modeled grid-cell data, not a station observation in every barangay. The 2018–2019 weather fields are missing for 1,056 barangay-month rows and are imputed in the training pipeline. Compare with PAGASA or another authorized source before operational claims."],
], [1.12 * inch, 2.5 * inch, 2.58 * inch]), Spacer(1, 6)]
story += [
    P("The 50 proposed participants are for usability evaluation only. They are not the number of model-training observations. The source line list is aggregated to monthly barangay counts for modeling.", body),
    P("Before operational use, document CHO authorization and approved data transfer/storage, the case-definition version, report-received dates, duplicate review using a stable de-identified key, reporting completeness, and the retention/deletion schedule. Continue to distinguish a confirmed zero from a missing report.", body),
    PageBreak(),
]

story += [P("Training procedure and risk definitions", h1), P("Printed pages 42–49: replace random splitting, same-month labels, and unsupported claims", small)]
story += [
    P("<b>Model target.</b> The production estimator is a RandomForestRegressor. It estimates next-month recorded case counts, not a direct categorical risk label. The system applies the predicted-count cutoff of 3 after estimating the count. For evaluation, the actual target is labelled a hotspot at 2 or more recorded cases. The historical map uses separate historical count bands.", body),
    P("<b>Predictors.</b> The saved model uses barangay, year and month, the issue-month recorded count, rainfall, mean temperature, humidity, representative-point coordinates, prior case counts at lags 1, 2, 3, 6 and 12 months, 3- and 6-month rolling case means, one-month weather lags, and month-of-year sine/cosine features. Blood type is not a model input. Patient symptoms and individual records are not model features.", body),
    P("<b>Chronological split.</b> All barangays from a reference month stay in the same partition. The outer split uses earlier months for model development and later months for final testing. The development portion is then split into training and validation:", body),
    table([
        ["Partition", "Reference months", "Rows", "Share of usable rows", "Use"],
        ["Training", "2018-02 to 2022-10", "2,508", "56.44%", "Fit model and preprocessing."],
        ["Validation", "2022-11 to 2024-05", "836", "18.81%", "Select model settings; not final test."],
        ["Final test", "2024-06 to 2026-06", "1,100", "24.75%", "Evaluate targets from 2024-07 to 2026-07."],
    ], [0.78 * inch, 1.35 * inch, 0.58 * inch, 1.0 * inch, 2.49 * inch]), Spacer(1, 7),
    P("The model uses 75.25% of usable rows for development (training plus validation) and 24.75% for the later test period. The development rows are further divided into training and validation; therefore the final table is not a simple 80/20 random split. The later period has been viewed in earlier project iterations and is not an untouched independent test for future changes.", body),
    P("Preprocessing, including missing-value imputation and barangay encoding, is fitted on the training data only for model selection. Hyperparameters are selected on validation data. Test rows are not used to fit preprocessing or select parameters. The saved selected parameters are 500 trees, maximum depth 10, minimum leaf size 8, and max_features 0.8. Use only information available at each forecast issue cutoff.", body),
    P("<b>Risk descriptions.</b> The map’s historical bands are project display labels, not verified CHO/DOH classifications: zero recorded cases; Low 1–5; Moderate 6–50; High 51–100; Critical 101+. The forecast review rule and observed-hotspot label are separate: predicted count ≥3 triggers planning review; actual count ≥2 is the positive class used for evaluation.", body),
    PageBreak(),
]

story += [P("Chapter 4 model evaluation results", h1), P("Add as a results section; these are the latest saved system metrics", small)]
story += [
    P("The final test partition contains 1,100 barangay-month predictions. The Random Forest regression model estimates the next-month recorded case count. For hotspot metrics, predicted counts of 3 or more are treated as positive planning-review flags, while observed counts of 2 or more are labelled positive hotspots.", body),
    table([
        ["Metric", "Formula", "Current result"],
        ["MAE", "sum(abs(y - yhat)) / n", "1.8802 cases"],
        ["RMSE", "sqrt(sum((y - yhat)^2) / n)", "2.8917 cases"],
        ["R-squared", "1 - sum((y - yhat)^2) / sum((y - ybar)^2)", "0.6012"],
        ["Hotspot precision", "TP / (TP + FP)", "396 / (396 + 69) = 85.16%"],
        ["Hotspot recall", "TP / (TP + FN)", "396 / (396 + 143) = 73.47%"],
        ["Hotspot F1", "2 × (precision × recall) / (precision + recall)", "78.88%"],
        ["Accuracy", "(TP + TN) / n", "(396 + 492) / 1,100 = 80.73%"],
    ], [1.05 * inch, 2.55 * inch, 2.6 * inch]), Spacer(1, 8),
    P("<b>Confusion matrix (actual rows × predicted columns)</b>", h2),
    table([
        ["", "Predicted not hotspot", "Predicted hotspot"],
        ["Actual not hotspot", "TN = 492", "FP = 69"],
        ["Actual hotspot", "FN = 143", "TP = 396"],
    ], [1.65 * inch, 2.2 * inch, 2.2 * inch], center_cols=(1, 2)), Spacer(1, 8),
    table([
        ["Class", "Precision", "Recall", "F1", "Support"],
        ["Not hotspot", "77.48%", "87.70%", "82.27%", "561"],
        ["Hotspot", "85.16%", "73.47%", "78.88%", "539"],
    ], [1.35 * inch, 1.1 * inch, 1.1 * inch, 1.0 * inch, 1.5 * inch], center_cols=(1, 2, 3, 4)),
    PageBreak(),
]

story += [P("How to interpret the results", h1)]
story += [
    P("The saved test precision is above 85% at 85.16%, using the fixed internal rules above. This means 396 of the 465 predicted hotspot flags were actual hotspots in this historical test partition. It does not mean that 85% of all cases were predicted correctly, and it does not guarantee the same result on future months.", body),
    P("The model missed 143 of 539 observed hotspots. Its hotspot recall is 73.47%, so about 26.53% of observed hotspots were not flagged. Precision should therefore be reported together with recall and F1, not by itself.", body),
    table([
        ["Forecast method", "MAE", "RMSE", "Hotspot precision", "Hotspot recall", "Hotspot F1"],
        ["Random Forest", "1.8802", "2.8917", "85.16%", "73.47%", "78.88%"],
        ["Persistence (previous count)", "1.8900", "3.1584", "85.65%", "69.76%", "76.89%"],
        ["Same month last year", "3.3382", "5.2626", "67.46%", "78.48%", "72.56%"],
        ["Trailing 3-month mean", "1.8403", "3.0077", "86.79%", "68.27%", "76.43%"],
    ], [1.47 * inch, 0.72 * inch, 0.78 * inch, 1.05 * inch, 0.95 * inch, 0.98 * inch], center_cols=(1, 2, 3, 4, 5)), Spacer(1, 8),
    P("For count forecasting, the Random Forest has lower RMSE than all listed baselines, but its MAE is higher than the trailing-three-month mean. For hotspot detection, Random Forest has higher overall F1 than persistence and the trailing-three-month mean, but its precision is lower than both of those baselines. Results also vary across later test blocks. The current evidence is mixed; it does not establish that the model is consistently better than simple methods.", body),
    P("The final test period was not used for parameter selection within the saved run, but the project team has inspected it in earlier work. Describe it as a chronological later-period test/holdout that has previously been viewed, not as an untouched independent test. Collect a new future period for independent confirmation. Until that is available, keep the forecast in planning-support status and require CHO review before operational decisions or resident alerts.", body),
    PageBreak(),
]

story += [P("System architecture, database, and privacy", h1), P("Printed pages 50–63 and 65: align the paper with configured components", small)]
story += [
    P("The current prototype uses Python, Django, Django’s ORM, and SQLite for the web system’s local development database. The machine-learning pipeline uses pandas and scikit-learn. The companion mobile client uses Expo and React Native and communicates with the system through its API. Do not describe Cloud Firestore as the primary relational database for this configured version. State a production database only after it has been selected and deployed.", body),
    P("The source line list contains individual case records. Model observations are derived monthly aggregates: one row for each barangay and month, with a recorded case count and lagged inputs. Keep individual case records, monthly aggregate features, weather rows, resident environmental reports, and forecast results as distinct data concepts. A resident environmental report is not a dengue case and does not increase the model’s case count unless CHO separately records and confirms a case.", body),
    *bullets([
        "Use a consistent integer Barangay primary key and integer foreign keys in Purok, case, weather, and other linked records.",
        "Keep diagnostic status (for example, suspected or confirmed) separate from patient outcome (for example, recovered). Describe only fields that exist in the Django models as implemented; label recommended forecast provenance fields as future additions if they are not stored yet.",
        "Django stores passwords using password hashing; do not say passwords are stored as reversible encrypted text.",
        "The forecast result should be reproducible from its issue date, input cutoff, target month, predicted count, threshold, and model version. If any of these fields are not currently stored, list them as a system improvement rather than a completed feature.",
        "Show only aggregated barangay-level results in public views. Restrict identifiable case details to authorized health personnel, and document CHO-approved retention and deletion procedures.",
    ]),
    P("CHO review and alerts", h2),
    P("The system requires CHO review before an alert is published to residents. A forecast is not itself an alert, a confirmed case, or an outbreak declaration. City and barangay workers can review information within their assigned roles; public alerts need an authorized review note and approval. Keep resident environmental observations in their own review workflow.", body),
    P("The current feature list excludes blood type, symptoms, and other patient-level clinical details from model inputs. Blood type may be shown only in permitted aggregate historical displays; it is not used to set a person’s risk or diagnosis. Explain the transformation from the line list to aggregated barangay-month counts and avoid publishing names, exact home addresses, or individual case details.", body),
    PageBreak(),
]

story += [P("Usability plan and SUS scoring", h1), P("Printed pages 66–73: replace the inconsistent participant allocations and scoring table", small)]
story += [
    P("The proposed 50 participants evaluate system usability and task performance only. They do not provide training observations for the prediction model. Use one allocation throughout the paper:", body),
    table([
        ["Participant group", "Number"],
        ["CHO staff", "5"],
        ["City Health Workers", "5"],
        ["Barangay Health Workers", "10"],
        ["LGU representatives", "5"],
        ["Residents", "25"],
        ["Total", "50"],
    ], [4.6 * inch, 1.6 * inch], center_cols=(1,)), Spacer(1, 8),
    P("For usability, record whether participants complete assigned tasks, the time taken, and errors. Use scenarios that match each role, such as submitting or reviewing a case, viewing the barangay map, checking an alert, and reviewing a report. These measures describe system use, not prediction accuracy.", body),
    P("<b>Standard SUS score.</b> Use the ten standard questions with five response choices scored from 1 to 5. For items 1, 3, 5, 7, and 9, contribution = response − 1. For items 2, 4, 6, 8, and 10, contribution = 5 − response. Add all ten contributions and multiply by 2.5. The resulting SUS score ranges from 0 to 100. Do not calculate standard SUS as an average of 1–5 ratings. If the researchers also use a custom acceptability questionnaire, name it separately and report its analysis separately.", body),
    P("Attach the actual SUS questionnaire and task scenarios to the appendices. Do not claim that the system increases awareness or prevents outbreaks unless those outcomes are measured using an appropriate design.", body),
    PageBreak(),
]

story += [P("Final consistency edits before submission", h1)]
story += bullets([
    "Remove the unsupported 338,983-to-62,313 comparison or replace it only after checking that the dates and geographic coverage match the cited official source.",
    "Check the in-text Acharjee et al. citation against reference [32] and verify the neural-network review description against reference [35]. Update the citation and reference list only after checking the source itself.",
    "Define DengueWatch as the project developed by the authors; do not cite a general dengue information page as the source of the project name.",
    "Use past tense for completed work and future tense for procedures that have not yet been carried out. Remove repeated model-training text and keep one copy of every data-dictionary field.",
    "Replace the side-rotated or unreadable diagrams with clearly oriented, larger versions. After replacement, renumber figures and tables and check every cross-reference.",
    "Use the terms ‘historical map risk band’, ‘observed hotspot label’, and ‘predicted planning-review flag’ for their distinct meanings. Do not call all of them one official risk classification.",
])
story += [P("The revised results describe the saved model evaluation and its limitations. They do not claim operational readiness. A future independent evaluation requires a new later period, stable CHO case definitions and reporting records, and comparison with the same simple baselines.", body)]

doc.build(story)

original = PdfReader(str(SOURCE))
insert = PdfReader(str(INSERT))
writer = PdfWriter()
for page in original.pages:
    writer.add_page(page)
for page in insert.pages:
    writer.add_page(page)
with OUTPUT.open("wb") as target:
    writer.write(target)
print(f"Wrote {OUTPUT} ({len(original.pages)} original + {len(insert.pages)} red replacement pages)")
