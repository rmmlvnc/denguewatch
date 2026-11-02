from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(r"C:\Users\miche\PRE-SYSTEM")
INPUT_PAPER = Path(r"C:\Users\miche\Downloads\dungogpueblos_ Capstone (4).pdf")
OUTPUT = ROOT / "output" / "pdf" / "DengueWatch_Capstone_Model_Comparison_Red.pdf"
SUPPLEMENT = ROOT / "tmp" / "capstone_revision_insert_pages.pdf"
DIAGRAM = ROOT / "tmp" / "capstone_replacement_diagrams.pdf"

RED = colors.HexColor("#B42318")
PALE_RED = colors.HexColor("#FFF4F2")
INK = colors.HexColor("#172B3A")
MUTED = colors.HexColor("#5F6B76")
GREEN = colors.HexColor("#0F766E")
WHITE = colors.white


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="GuideTitle", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=20, leading=25, textColor=INK, alignment=TA_LEFT, spaceAfter=12,
))
styles.add(ParagraphStyle(
    name="SectionHead", parent=styles["Heading2"], fontName="Helvetica-Bold",
    fontSize=13, leading=17, textColor=INK, spaceBefore=8, spaceAfter=7,
))
styles.add(ParagraphStyle(
    name="Location", parent=styles["Normal"], fontName="Helvetica-Bold",
    fontSize=9, leading=12, textColor=MUTED, spaceAfter=5,
))
styles.add(ParagraphStyle(
    name="Revision", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=9.4, leading=13.3, textColor=RED, spaceAfter=6,
))
styles.add(ParagraphStyle(
    name="RevisionSmall", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=8.1, leading=10.5, textColor=RED, spaceAfter=3,
))
styles.add(ParagraphStyle(
    name="RevisionBullet", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=9.2, leading=12.5, textColor=RED, leftIndent=14,
    firstLineIndent=-8, spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="TableHeadRed", parent=styles["Normal"], fontName="Helvetica-Bold",
    fontSize=8.1, leading=10, textColor=RED,
))
styles.add(ParagraphStyle(
    name="TableCellRed", parent=styles["Normal"], fontName="Helvetica",
    fontSize=7.8, leading=10, textColor=RED,
))
styles.add(ParagraphStyle(
    name="CaptionRed", parent=styles["Normal"], fontName="Helvetica-Oblique",
    fontSize=8.5, leading=11, textColor=RED, alignment=TA_CENTER, spaceBefore=5,
))


def para(text: str, style: str = "Revision") -> Paragraph:
    return Paragraph(text, styles[style])


def bullets(items: list[str]) -> list[Paragraph]:
    return [para("&#8226; " + item, "RevisionBullet") for item in items]


def make_table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    converted = []
    for row_index, row in enumerate(rows):
        style = "TableHeadRed" if header and row_index == 0 else "TableCellRed"
        converted.append([Paragraph(cell, styles[style]) for cell in row])
    table = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BACKGROUND", (0, 0), (-1, 0), PALE_RED if header else WHITE),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E8C8C4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def footer(c: canvas.Canvas, doc) -> None:
    c.saveState()
    c.setStrokeColor(colors.HexColor("#D7DEE3"))
    c.line(0.6 * inch, 0.55 * inch, 7.9 * inch, 0.55 * inch)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(0.65 * inch, 0.35 * inch, "Red replacement text for adviser review - original paper pages are retained")
    c.drawRightString(7.85 * inch, 0.35 * inch, f"Revision insert {doc.page}")
    c.restoreState()


story = []
story += [para("DENGUEWATCH CAPSTONE - RED REVISION INSERTS", "GuideTitle")]
story += [para(
    "This working copy keeps the submitted capstone pages unchanged and adds the revised text in red at the end. "
    "The source provided was a PDF, so these red sections are ready-to-paste replacements rather than edits inside the original paragraphs. "
    "Use the original page references below to replace the matching text in the editable manuscript. Do not keep both versions of a replaced paragraph.",
    "Revision",
)]
story += [para("Replacement sections included", "SectionHead")]
story += bullets([
    "Chapter 1: correct the dengue statistic, use measurable objectives, define the forecast, and simplify key terms.",
    "Chapter 3: update the data inventory, the model target, the chronological split, the evaluation results, the database description, and the privacy plan.",
    "Usability: use one 50-person allocation, standard SUS scoring, separate custom ratings, and clear user tasks.",
    "Related studies: correct the highlighted descriptions and reference details.",
    "Two landscape diagrams are included as suggested replacements for the small or sideways workflow figures.",
])
story += [para(
    "Numbers in these revisions come from the current project validation report and data inventory. The manuscript must describe the CHO file access and case definition as documented by the authors; the inventory does not contain a signed data-sharing agreement or a CHO case-definition guide.",
    "Revision",
)]
story += [PageBreak()]

# Chapter 1 - Introduction, objectives, scope, and definitions.
story += [para("1. Chapter 1 - Introduction statistic", "SectionHead")]
story += [para("Replace the incorrect first-quarter comparison on original page 3 with this sentence:", "Location")]
story += [para(
    "The Department of Health reported 62,313 dengue cases from January 1 to March 1, 2025. "
    "This was 73% higher than the same period in 2024 [3]. This comparison shows why local health teams need timely case information.",
)]
story += [para(
    "Delete the statement that compares 62,313 with 338,983 as if both numbers covered the same first-quarter period. "
    "Keep the dates and period exactly as stated by the cited source.",
)]

story += [para("2. Chapter 1 - Objectives of the study", "SectionHead")]
story += [para("Replace the objectives on original page 7 with this measurable set:", "Location")]
story += [para(
    "The study will develop and evaluate DengueWatch, a web and mobile system for dengue reporting, historical mapping, and next-month case forecasting in Iligan City. The study will:",
)]
story += bullets([
    "Build digital reporting and monitoring features, then measure task completion, entry errors, and time needed to report a case.",
    "Train a Random Forest regression model to estimate the next month's recorded case count for each barangay, then compare it with simple forecasts using later time periods.",
    "Check the map, reporting, and alert features using written test cases and record whether each test passes.",
    "Measure usability with task results and a correctly scored System Usability Scale (SUS). Report any custom feedback survey separately.",
])
story += [para(
    "The study will not claim that a usability test proves that dengue outbreaks were prevented. Lower outbreak rates may be a possible long-term benefit, but this study is not designed to measure that outcome.",
)]

story += [para("3. Chapter 1 - Scope and limitations", "SectionHead")]
story += [para("Replace the prediction description on original pages 8-9 with this text:", "Location")]
story += [para(
    "DengueWatch is a web and mobile system for dengue monitoring in Iligan City. Its forecast is a count-prediction task. "
    "At a forecast cutoff during month t, the model uses case and weather information available by that cutoff to estimate the number of recorded dengue cases in month t+1 for each of the city's 44 barangays. One prediction represents one barangay for one calendar month. The target is the next month's recorded case count, not a risk label made from the same month's count.",
)]
story += [para(
    "The model uses past case counts and lags, calendar information, monthly rainfall, mean temperature, mean relative humidity, and barangay location. It does not use a patient's blood type, symptoms, or other individual medical details to predict a barangay's next-month count. A predicted count of six or more is flagged as a potential planning hotspot. Six is an internal project cutoff, not an official Department of Health outbreak definition.",
)]
story += [para(
    "The historical map and the forecast are different views. The historical map shows case records for the selected year or for all available years. The forecast view estimates next-month counts. A historical total across a year or several years must not be described as a next-month forecast. Purok or street details are descriptive map information; the model prediction unit remains the barangay-month.",
)]
story += [para(
    "DengueWatch uses these four display bands for counts: Low is 1-5, Moderate is 6-50, High is 51-100, and Critical is 101 or more. A count of zero is shown as zero or no recorded cases; a missing report is shown as missing data. These bands are internal display rules and are not official DOH classifications. If the team wants zero counts to receive the Low label, the application and paper must both be updated to use that same rule.",
)]
story += [para(
    "The case source is an individual line list. The authors identify the 2018-2019 files as CHO records, but a signed access or data-sharing document was not included in the reviewed inventory. The source does not include a case-definition version, a received/report-entry date, or a stable case identifier. For these reasons, the model target should be called recorded case counts until CHO confirms the case definition and reporting process.",
)]
story += [para(
    "The project uses monthly weather values from Open-Meteo historical data. These are model-grid estimates, not measurements from a weather station in every barangay. The current source has missing weather values for 2018 and 2019, and 44 barangay points map to eight distinct returned grid cells. Missing weather values are imputed by the trained pipeline; they are not treated as observed weather. The model does not use population denominators, so its outputs are counts, not population-adjusted rates.",
)]
story += [para(
    "A month with no case rows is treated as zero only under the authors' statement that the CHO data are complete. The project does not have a separate CHO zero-report register to verify every zero. The current holdout period has already been inspected during earlier project work, so it cannot be called an untouched test for later experiments. Forecasts are planning support only. CHO or health personnel must review them and confirm cases before any public alert or operational action.",
)]

story += [para("4. Chapter 1 - Definition of DengueWatch", "SectionHead")]
story += [para("Replace the DengueWatch definition on original page 12:", "Location")]
story += [para(
    "DengueWatch. The web and mobile system developed in this capstone to collect dengue reports, show historical case maps, estimate next-month barangay case counts, and share health information for Iligan City. This is the name of the project, so it does not need a Cleveland Clinic citation.",
)]
story += [para(
    "Remove reference [14] if it is used only for this project name. If it is used elsewhere, keep it only where it supports the specific health information in that sentence, and renumber the references after any deletion.",
)]
story += [PageBreak()]

# Data feasibility and modeling details.
story += [para("5. Chapter 3 - Data feasibility plan", "SectionHead")]
story += [para("Replace the old inventory table on original pages 29-35 with this updated summary:", "Location")]
story += [make_table([
    ["Inventory item", "Current source information", "What must be checked or stated"],
    ["Years and reporting frequency", "14,174 individual case records cover 2018-01-01 to 2026-07-31. The active file combines the 2018, 2019, and 2020-2026 sources. Each record has an admission date; a separate received/reported date is not supplied.", "Report the admission-date range and the missing report-date field. Reporting delay cannot be calculated from the current files."],
    ["Places and usable observations", "The source includes 44 official Iligan barangays. 13,967 line-list rows have both a valid admission date and an official barangay. The monthly panel has 4,532 barangay-month cells (44 barangays x 103 months); 4,444 rows are usable for the current model after targets/features are prepared.", "The panel runs January 2018-July 2026. Some line-list rows cannot be assigned to a mapped barangay or month and are excluded from model rows."],
    ["Record type", "The source is an individual case line list, not a table of monthly totals. The model aggregates records into case counts by barangay and month.", "Do not describe the source rows as aggregated counts or the model rows as individual patients."],
    ["Missing fields and unmatched rows", "The audit flags 810 rows with one or more blank requested fields, 74 rows without an official barangay match, 133 rows without a valid admission date, and 34 Year/admission-date disagreements. These categories may overlap.", "Describe missingness by field where possible. Unmatched/date-invalid lines cannot be placed in a barangay-month model row."],
    ["Duplicates and case definition", "174 exact-repeat extra rows are flagged and retained. No stable case ID is supplied. The file does not state a versioned CHO case definition or confirmed/suspected status rules.", "Do not delete suspected duplicates without CHO review. Obtain the case definition and a de-identified stable ID before final duplicate resolution."],
], [1.0*inch, 2.75*inch, 3.05*inch])]
story += [PageBreak()]
story += [para("5A. Data feasibility plan - continued", "SectionHead")]
story += [para("Complete the inventory with reporting, access, and weather details:", "Location")]
story += [make_table([
    ["Inventory item", "Current source information", "What must be checked or stated"],
    ["Zero versus no report", "The team stated that the CHO datasets are complete; on that basis, 1,379 empty monthly panel cells were filled as zero.", "There is no separate CHO zero-report register in the inventory. Treat zero as an assumption based on the team's confirmation, not an independently verified fact. A missing submission must remain missing, not zero."],
    ["Modeling unit and frequency", "The current model uses one row per barangay per calendar month and predicts the following month's recorded case count. The monthly panel contains 4,444 usable rows.", "The adviser suggests weekly rows as a possible design. Use weeks only after defining a weekly forecast target/horizon and verifying weekly reporting completeness. Do not mix weekly inputs with the current monthly target."],
    ["CHO access", "The authors identify the 2018-2019 files as CHO records and confirm completeness. The inventory does not contain signed access or data-sharing documentation.", "Record the CHO approval, authorized users, transfer/storage method, permitted use, retention, and deletion process. Do not describe formal access as confirmed until documented."],
    ["Weather source and matching", "Open-Meteo historical archive estimates: monthly precipitation sum (mm), mean temperature (degrees C), and mean relative humidity (%). One boundary-derived representative point was requested per barangay; 44 points returned eight distinct grid cells.", "All 24 months in 2018-2019 are missing weather (1,056 barangay-month rows). Grid values are estimates, not local station observations; neighboring barangays can share a grid cell. The archive may use different model resolutions by period."],
], [1.0*inch, 2.75*inch, 3.05*inch])]
story += [Spacer(1, 7)]
story += [para(
    "For this study, keep the current monthly design: one row represents one barangay in one calendar month, including months recorded as zero under the stated completeness assumption. The model predicts the recorded case count for the next month. A weekly model is a future option only; it would need a weekly target, a weekly completeness check, and a new chronological evaluation. The proposed 50 people are for usability testing only; they are not the number of training records.",
)]
story += [para(
    "Before further model development or operational use, complete the inventory with CHO-approved access arrangements, the official case definition, report-received dates, a stable de-identified case key, and a zero-report register or another documented way to tell a true zero from a missing report. Confirm duplicate handling and retention/deletion rules with the CHO. Compare Open-Meteo estimates with PAGASA or other authorized station data before calling them locally verified.",
)]

story += [PageBreak()]
story += [para("6. Chapter 3 - Forecast target and validation", "SectionHead")]
story += [para("Replace the training and evaluation description on original pages 42-49 with this text:", "Location")]
story += [para(
    "DengueWatch uses a Random Forest regressor. At a forecast cutoff in month t, it estimates the recorded case count for each barangay in month t+1. The model input contains only values available by the cutoff. The next month's outcome is used only as the target. Preprocessing steps are fitted on training rows and then applied to validation and later rows. Every barangay from the same reference month stays in the same time partition.",
)]
story += [make_table([
    ["Partition", "Reference months", "Rows", "Share", "Use"],
    ["Training", "2018-02 to 2023-01", "2,640", "59.4%", "Fit preprocessing and candidate models."],
    ["Validation", "2023-02 to 2024-09", "880", "19.8%", "Choose model settings and conduct exploratory checks."],
    ["Later-period holdout", "2024-10 to 2026-06", "924", "20.8%", "Historical evaluation. This period has already been viewed in earlier project iterations."],
], [1.15*inch, 1.55*inch, 0.7*inch, 0.65*inch, 2.75*inch])]
story += [Spacer(1, 7)]
story += [para(
    "These percentages show how the 4,444 usable rows were split. They are not performance scores. Training targets are one month after their reference month. The later-period holdout predictions cover target months November 2024-July 2026. Because the holdout has been inspected, new model or cutoff changes must be tested on a new later period before being described as independent confirmation.",
)]
story += [para(
    "The selected Random Forest regressor uses 300 trees, a minimum of two rows per leaf, and max_features=0.8. Candidate settings are selected using training and validation data. The final held-out period must not be used to choose a cutoff or tune parameters.",
)]
story += [para("Count forecast results on the previously evaluated later-period holdout:", "Revision")]
story += [make_table([
    ["Measure", "Random Forest", "Persistence baseline", "What it means"],
    ["MAE", "1.8483 cases", "1.7078 cases", "The model's average absolute error is higher, so it is worse on MAE."],
    ["RMSE", "2.7051 cases", "2.8634 cases", "The model's RMSE is lower, so it does better on this measure."],
], [0.8*inch, 1.15*inch, 1.4*inch, 3.45*inch])]
story += [Spacer(1, 5)]
story += [para(
    "MAE = the average of the absolute difference between each actual count and its predicted count. RMSE = the square root of the average squared difference. Lower values are better. The model has lower RMSE but higher MAE than persistence, so it does not beat that simple baseline on both measures.",
)]
story += [para(
    "For the hotspot task, an observed barangay-month is a hotspot when it has at least six recorded cases. The model's predicted count is turned into a predicted hotspot using the same six-case cutoff.",
)]
story += [make_table([
    ["Actual / predicted", "Not a hotspot", "Hotspot"],
    ["Not a hotspot", "717 true negatives", "71 false alarms"],
    ["Hotspot", "28 missed hotspots", "108 true positives"],
], [2.0*inch, 2.0*inch, 2.0*inch])]
story += [Spacer(1, 5)]
story += [para(
    "Precision = TP / (TP + FP) x 100 = 108 / (108 + 71) x 100 = 60.34%. It tells how many predicted hotspot flags were correct. Recall = TP / (TP + FN) x 100 = 108 / (108 + 28) x 100 = 79.41%. It tells how many observed hotspots were found. F1 = 68.57%. Report all three with the 924-row holdout and the six-case definition; do not call this an accuracy percentage.",
)]
story += [para(
    "Simple forecasts were also compared: persistence carries forward this month's count; seasonal naive uses the same month from the previous year; and the trailing-three-month mean uses the prior three months. The Random Forest does not beat all simple forecasts in every later test block. Keep the results as planning support only, not as a validated outbreak warning system.",
)]
story += [para(
    "A separate exploratory validation analysis tried a higher predicted-count cutoff of ten. It flagged 48 barangay-months: 41 true positives and 7 false alarms. Precision was 85.42%, but recall was only 15.83% because 218 of 259 observed hotspots were missed. This is validation performance from an exploratory threshold test, not the live six-case result and not a final test score. Do not claim an 85% future precision guarantee.",
)]
story += [para("6B. Additional rolling validation experiment", "SectionHead")]
story += [para(
    "The team also compared settings over four forward-moving validation windows. Each window contains eight months, all barangays from one month stay together, and preprocessing is fitted on the earlier training rows only. No later-period holdout rows were used for feature engineering, fitting, tuning, or scoring. The development period has already been used in earlier model choices, so these results are exploratory.",
)]
story += [make_table([
    ["Candidate / baseline", "MAE", "RMSE", "R-squared", "Hotspot precision / recall / F1"],
    ["Current Random Forest", "2.1622", "3.6238", "0.4912", "68.25% / 56.67% / 61.92%"],
    ["Conservative Random Forest", "2.1207", "3.5819", "0.5029", "69.37% / 56.97% / 62.56%"],
    ["Conservative Random Forest, no weather", "2.0849", "3.5399", "0.5145", "71.32% / 55.76% / 62.59%"],
    ["Broader-feature Random Forest", "2.1378", "3.6097", "0.4952", "67.72% / 58.48% / 62.76%"],
    ["Poisson regression (alpha 0.1)", "2.6884", "8.2632", "-1.6454", "75.00% / 50.00% / 60.00%"],
    ["Poisson regression (alpha 1.0)", "2.8113", "9.4964", "-2.4939", "73.04% / 45.15% / 55.81%"],
    ["Poisson regression (alpha 10)", "2.6211", "6.0185", "-0.4033", "74.07% / 36.36% / 48.78%"],
    ["Persistence baseline", "2.2351", "3.8028", "0.4397", "67.08% / 66.06% / 66.56%"],
    ["Trailing 3-month mean", "2.0346", "3.4704", "0.5334", "71.18% / 62.12% / 66.34%"],
], [1.7*inch, 0.75*inch, 0.75*inch, 0.85*inch, 2.7*inch])]
story += [Spacer(1, 5)]
story += [para(
    "The conservative Random Forest without weather (500 trees, depth 10, minimum leaf size 4, max_features 0.8) had the lowest validation MAE among tested model candidates. Its precision (71.32%) was only slightly above the three-month baseline (71.18%), while its recall and F1 were lower. The broader-feature Random Forest had the highest Random Forest hotspot F1 and recall, but still trailed the baseline on both. Poisson regression was also tested with fold-fitted preprocessing; none of its settings beat the baseline overall, and its RMSE was substantially higher. Keep the current deployed model and holdout results unchanged. These previously explored windows are not an untouched test.",
)]
story += [para(
    "The team's 85% precision, recall, and F1 figures are development goals, not guaranteed outcomes. The validation results do not meet them. Do not raise the live forecast cutoff simply to display a larger precision percentage: a stricter cutoff can miss many observed hotspots. Keep the observed hotspot definition at six or more actual cases, report precision, recall, and F1 together, and assess any future candidate on a newly collected untouched period before operational use.",
)]
story += [PageBreak()]

# Risk rule and model input explanation.
story += [para("6A. One definition for hotspot and risk", "SectionHead")]
story += [para("Use this rule in the text, training diagram, database description, map labels, and alert process:", "Location")]
story += [para(
    "Forecast unit: one Iligan City barangay for one calendar month. Forecast horizon: one month ahead. Forecast target: the number of recorded case rows in the next month. A potential planning hotspot is a barangay with a predicted count of six or more cases in that next month. The map's historical layer shows observed records, not forecasts. Its period total must be labelled with the year or year range being shown. Purok counts are location details, not separate model predictions.",
)]
story += [make_table([
    ["Count band", "DengueWatch display label"],
    ["0-5", "Low for forecast output; show a zero count distinctly from a missing report."],
    ["6-50", "Moderate and meets the internal six-case planning cutoff."],
    ["51-100", "High."],
    ["101 or more", "Critical."],
], [1.45*inch, 4.55*inch])]
story += [Spacer(1, 5)]
story += [para(
    "These bands are project display rules, not DOH outbreak categories. For historical map filters, say whether the counts are for one year or all available years. Do not present a multi-year total as a monthly risk estimate. Until the application and CHO reporting process can distinguish a verified zero from a missing report, label missing reports as no data instead of zero.",
)]
story += [para(
    "Do not use ordinary random cross-validation for this time-ordered task. Use a chronological split. Use only issue-time information in features. Fit learned imputation and encoding steps on training rows only. Compare the model with simple forecasts on later periods. Report count MAE/RMSE separately from hotspot precision, recall, F1, and the confusion matrix. A usability score cannot show that predictions are accurate.",
)]

# Database and software architecture.
story += [para("7. Chapter 3 - Database and technical architecture", "SectionHead")]
story += [para("Replace the conflicting database/software descriptions on original pages 50-63 with this explanation:", "Location")]
story += [para(
    "The current prototype uses Python, Django, Django's relational data models, and an SQLite database for local development. The machine-learning pipeline is built with pandas and scikit-learn. The model input is a separate monthly CSV created from the case line list, weather values, and barangay information. Do not describe Firestore as the main database unless the implementation is changed and verified. A messaging service may be used to deliver notifications, but it is not the case-record database.",
)]
story += [make_table([
    ["Record", "Clear unit and relationship"],
    ["Barangay", "One row per official barangay; integer primary key."],
    ["Purok", "One row per purok; integer primary key and integer barangay foreign key."],
    ["User account", "One account per user; roles and location links use foreign keys. Store passwords using Django's secure password hashing, not reversible encryption."],
    ["Dengue case", "One row per individual case record. Keep patient details in this restricted table. Do not use an unrestricted case_count to represent several people in a row that has one person's age or sex. If aggregated reports are needed, store them in a separate aggregate table."],
    ["Case classification and outcome", "Keep diagnostic status (for example, suspected or confirmed) separate from outcome status (for example, recovering, recovered, or deceased). Use the CHO's actual definitions."],
    ["Monthly model row", "One row per barangay-month, with an aggregate case count and the weather and location features for that month. It is a model input, not one individual patient."],
    ["Weather record", "Store the observation month, rainfall in millimeters, mean temperature in degrees Celsius, mean relative humidity in percent, barangay or grid coordinates, and source."],
    ["Forecast record", "For reproducibility, record issue date, target month, barangay, predicted count, threshold used, risk label, model version, and CHO review status. Add these fields to the database before claiming they are stored by the current prototype."],
], [1.55*inch, 4.45*inch])]
story += [Spacer(1, 6)]
story += [para(
    "Use one integer type for each barangay key and its foreign-key references. In the Purok description, refer to barangay_id consistently. In the Hotspot Prediction description, list risk_level and analysis_remarks once each. Do not describe the Integrated Dataset as one row linked to one case if it actually represents a barangay-month aggregate. Update the ERD and data dictionary to match these units and the Django models.",
)]
story += [para(
    "The forecast record fields above are requirements for reproducible future forecasts. If the prototype has not yet saved the issue date, target month, model version, or CHO review information, describe these as planned fields, not completed system functions.",
)]
story += [PageBreak()]

# Usability and evaluation.
story += [para("8. Chapter 3 - Usability evaluation and participants", "SectionHead")]
story += [para("Use one planned sample allocation throughout the paper. The following keeps the later page's total of 50:", "Location")]
story += [make_table([
    ["Participant group", "People", "Share"],
    ["City Health Office staff", "5", "10%"],
    ["City Health Workers", "5", "10%"],
    ["Barangay Health Workers", "10", "20%"],
    ["Local Government Unit representatives", "5", "10%"],
    ["Residents", "25", "50%"],
    ["Total", "50", "100%"],
], [3.2*inch, 1.0*inch, 1.0*inch])]
story += [Spacer(1, 5)]
story += [para(
    "The 50 participants are for usability evaluation only. They do not establish that the historical dataset is large enough to train the model. Confirm this planned allocation with the adviser before recruitment, and use the same allocation in every chapter and table.",
)]
story += [para("Use the following SUS procedure in place of the current 1-5 SUS interpretation table:", "Location")]
story += [para(
    "The System Usability Scale has ten standard statements. Each participant answers each item from 1 (strongly disagree) to 5 (strongly agree). Keep the standard questionnaire wording, or use a validated translation. Do not rewrite the SUS items in simple words and still call the result standard SUS; any changed questionnaire is a separate custom survey.",
)]
story += [para(
    "For odd-numbered SUS items, subtract 1 from the response. For even-numbered items, subtract the response from 5. Add the ten item scores and multiply the total by 2.5. This gives one SUS score from 0 to 100 for each participant. Report the mean SUS score and the number of completed questionnaires. Do not interpret a 1-5 average as a SUS score.",
)]
story += [para(
    "If the researchers also use a custom 5-point survey about function or acceptability, report those item means separately and call them custom survey results. SUS measures perceived usability; it does not measure forecast precision or outbreak prevention.",
)]
story += [para("Add these task scenarios to the appendix and use the same tasks during the usability session:", "Location")]
story += bullets([
    "Resident: open the map, find the barangay and month shown, read an alert, and submit an environmental observation. Confirm the observation is not described as a confirmed dengue case.",
    "Barangay Health Worker: submit a case report for the assigned barangay and purok, then find its review status.",
    "City Health Worker: search for a case report, check its details, and record the review outcome.",
    "CHO staff: review a forecast, compare it with the displayed historical count, and approve or withhold a public alert after checking the underlying information.",
    "LGU representative: choose a map period, identify a high-count barangay, and export or view a summary report.",
])
story += [para(
    "Record task completion, completion time, entry errors, help needed, and participant comments. Use these results to describe system usability and function only.",
)]

# Privacy, public alerts, records.
story += [para("9. Chapter 3 - Privacy and public alerts", "SectionHead")]
story += [para("Replace or expand the privacy text on original page 70 with this simple, specific plan:", "Location")]
story += [para(
    "The study will follow the Data Privacy Act and the approved school and CHO rules for handling health data. Only authorized staff will be able to view identifiable case records. Public maps and reports will show barangay-level totals and will not display patient names, contact details, or exact home locations. Patient details will be used only for permitted case review and research tasks.",
)]
story += [para(
    "The study team and CHO will approve a retention period before collecting or importing records. At the end of that period, identifiable copies will be securely deleted or handled as required by the approved records policy. The system will keep audit logs of access and important changes to case records and alerts.",
)]
story += [para(
    "Community environmental observations will be stored and reviewed separately from dengue case records. A resident observation does not create a confirmed dengue case. A forecast or risk label will not be published as a public alert until CHO or authorized health personnel review it and confirm the information needed for action. The system supports staff decisions; it does not replace medical or epidemiological judgment.",
)]
story += [para(
    "Do not claim a specific retention period, CHO approval, signed data-sharing agreement, or implemented audit feature unless the project has the required record or code evidence. State whether each control is implemented or planned.",
)]
story += [PageBreak()]

# Literature/reference fixes and readability notes.
story += [para("10. Chapter 2 - Correct the highlighted study summaries", "SectionHead")]
story += [para("Replace the Acharjee paragraph on original page 20 with this summary for reference [32]:", "Location")]
story += [para(
    "Sarma et al. [32] studied machine-learning methods for dengue prediction using patient diagnosis information from hospitals in Bangladesh. They compared a decision tree with a Random Forest and reported higher average accuracy for the decision tree. Their study used patient-level diagnosis data in a different setting. Its result should not be compared directly with DengueWatch, which estimates next-month case counts for Iligan City barangays.",
)]
story += [para("Replace the neural-network paragraph on original page 22 with this summary for the corrected reference [35]:", "Location")]
story += [para(
    "Lober, Rodrigues, and Roster [35] reviewed 62 studies of neural networks used to forecast dengue. The studies used different time periods, places, and model checks. Neural networks did not perform best in every comparison. This supports testing the DengueWatch model against simple forecasts using later local data instead of assuming that one algorithm will always be best. The cited article is a medRxiv preprint and has not been peer reviewed.",
)]
story += [para("Replace the reference entries as follows:", "Location")]
story += [para(
    "[32] Sarma, D., Hossain, S., Mittra, T., Bhuiya, M. A. M., Saha, I., &amp; Chakma, R. (2020). Dengue prediction using machine learning algorithms. In 2020 IEEE 8th R10 Humanitarian Technology Conference (R10-HTC), 1-6. https://doi.org/10.1109/R10-HTC49770.2020.9357035",
    "RevisionSmall",
)]
story += [para(
    "[35] Lober, L., Rodrigues, F. A., &amp; Roster, K. O. (2025). Neural networks for dengue forecasting: A systematic review [Preprint]. medRxiv. https://doi.org/10.1101/2025.10.14.25338016",
    "RevisionSmall",
)]
story += [para(
    "For the reference [14] attached to the student-created system name, remove the citation from the definition. Remove its reference-list entry if no other sentence uses it, then renumber later citations. Check every remaining cited claim against the source title, authors, year, and actual content. Do not keep a citation just because it appears in the current list.",
)]

story += [para("11. Chapter 3 - Layout and wording corrections", "SectionHead")]
story += [para("Use these finishing changes when applying the red text to the editable manuscript:", "Location")]
story += bullets([
    "Replace the sideways data-flow figure with the landscape diagram at the end of this file. Keep the labels large enough to read when printed.",
    "Replace or redraw the architecture figure with the landscape diagram at the end. Enlarge labels in the ERD and data dictionary.",
    "Check all figure numbers, table numbers, and in-text references after adding or removing a figure or table.",
    "Remove repeated methods paragraphs. Correct spelling such as 'AI-Asssited' and wording such as 'breed more faster'.",
    "Use future tense for work that is planned. Use past tense only for work that has already been completed.",
    "Use the same forecast horizon, one-barangay-month unit, six-case hotspot cutoff, and display bands wherever the model, diagrams, map, database, and alert process are described.",
])

doc = SimpleDocTemplate(
    str(SUPPLEMENT), pagesize=letter,
    rightMargin=0.65*inch, leftMargin=0.65*inch,
    topMargin=0.62*inch, bottomMargin=0.78*inch,
    title="DengueWatch Capstone Red Revision Inserts",
    author="OpenAI",
)
doc.build(story, onFirstPage=footer, onLaterPages=footer)


def draw_box(c, x, y, w, h, title, detail, fill=PALE_RED):
    c.setFillColor(fill)
    c.setStrokeColor(colors.HexColor("#D8A19A"))
    c.roundRect(x, y, w, h, 9, stroke=1, fill=1)
    c.setFillColor(RED)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + w/2, y + h - 18, title)
    c.setFont("Helvetica", 8.5)
    words = detail.split()
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if stringWidth(candidate, "Helvetica", 8.5) <= w - 20:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    start_y = y + h - 35
    for i, text in enumerate(lines[:4]):
        c.drawCentredString(x + w/2, start_y - i*11, text)


def arrow(c, x1, y1, x2, y2):
    c.setStrokeColor(GREEN)
    c.setFillColor(GREEN)
    c.setLineWidth(1.4)
    c.line(x1, y1, x2, y2)
    c.line(x2, y2, x2-6, y2+3)
    c.line(x2, y2, x2-6, y2-3)


def create_diagram_pdf():
    width, height = landscape(letter)
    buff = BytesIO()
    c = canvas.Canvas(buff, pagesize=(width, height))
    c.setTitle("Landscape replacement diagrams for DengueWatch")

    # Page 1: corrected model training and evaluation flow.
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.55*inch, height-0.55*inch, "Monthly forecast training and evaluation")
    c.setFillColor(RED)
    c.setFont("Helvetica", 9.5)
    c.drawString(0.55*inch, height-0.82*inch, "Replacement for the small or sideways training flow; red labels show revised study steps.")

    x0 = 0.55*inch
    gap = 0.32*inch
    box_w = 2.92*inch
    box_h = 1.15*inch
    y_top = height - 2.55*inch
    y_bottom = height - 4.35*inch
    titles = [
        ("1. Source data", "CHO-attributed individual case list; monthly weather; official barangay boundaries."),
        ("2. Prepare rows", "Aggregate to one barangay-month. Record zero or missing status separately."),
        ("3. Make features", "Use only case and weather information available at the forecast cutoff."),
        ("4. Split by time", "Train 2018-02 to 2023-01; validate to 2024-09; later holdout after that."),
        ("5. Fit and compare", "Fit preprocessing on training rows; compare Random Forest with simple forecasts."),
        ("6. Forecast and review", "Estimate next-month count; flag >=6; CHO reviews before public action."),
    ]
    top_positions = [x0 + index*(box_w+gap) for index in range(3)]
    bottom_positions = [x0 + (2-index)*(box_w+gap) for index in range(3)]
    for index in range(3):
        draw_box(c, top_positions[index], y_top, box_w, box_h, *titles[index])
        draw_box(c, bottom_positions[index], y_bottom, box_w, box_h, *titles[index+3])
        if index < 2:
            arrow(c, top_positions[index]+box_w+2, y_top+box_h/2,
                  top_positions[index]+box_w+gap-3, y_top+box_h/2)
            arrow(c, bottom_positions[index]-3, y_bottom+box_h/2,
                  bottom_positions[index]-gap+2, y_bottom+box_h/2)
    # The flow continues from feature creation down to the temporal split.
    arrow(c, top_positions[2]+box_w/2, y_top-3, bottom_positions[0]+box_w/2, y_bottom+box_h+3)
    c.setFillColor(RED)
    c.setFont("Helvetica", 9)
    c.drawString(0.6*inch, 0.85*inch, "Prediction target: recorded case count in the next calendar month for each of Iligan City's 44 barangays.")
    c.drawString(0.6*inch, 0.62*inch, "Report count MAE/RMSE and hotspot precision/recall/F1 separately. The previously viewed holdout is not a new untouched test.")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawRightString(width-0.55*inch, 0.35*inch, "Replacement diagram - landscape page")
    c.showPage()

    # Page 2: simplified system architecture and data separation.
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.55*inch, height-0.55*inch, "DengueWatch system and data flow")
    c.setFillColor(RED)
    c.setFont("Helvetica", 9.5)
    c.drawString(0.55*inch, height-0.82*inch, "Replacement architecture diagram; case reports, community observations, and forecasts are kept distinct.")

    # Actors on left.
    actor_x, actor_w, actor_h = 0.65*inch, 1.85*inch, 0.57*inch
    actor_y_values = [height-1.85*inch, height-2.62*inch, height-3.39*inch]
    for label, ay in zip(["CHO / CHW / BHW staff", "LGU staff", "Residents"], actor_y_values):
        draw_box(c, actor_x, ay, actor_w, actor_h, label, "Role-based access", fill=colors.HexColor("#F2FAF8"))

    app_x, app_w = 3.35*inch, 2.15*inch
    draw_box(c, app_x, height-2.95*inch, app_w, 1.55*inch, "Django web and mobile system",
             "Case entry and review; historical map; next-month forecast; notifications; reports.", fill=colors.HexColor("#F2FAF8"))
    for ay in actor_y_values:
        arrow(c, actor_x+actor_w+3, ay+actor_h/2, app_x-5, height-2.95*inch+0.78*inch)

    db_x, db_w = 6.35*inch, 1.75*inch
    draw_box(c, db_x, height-1.98*inch, db_w, 0.95*inch, "Relational database",
             "SQLite in the local prototype; restricted identifiable case records.")
    draw_box(c, db_x, height-3.45*inch, db_w, 0.95*inch, "Monthly model input",
             "One row per barangay-month; weather and location features.")
    draw_box(c, db_x, height-4.92*inch, db_w, 0.95*inch, "Forecast review gate",
             "Predicted count and threshold; authorized health-personnel review.")
    arrow(c, app_x+app_w+3, height-2.15*inch, db_x-5, height-1.55*inch)
    arrow(c, app_x+app_w+3, height-2.25*inch, db_x-5, height-2.95*inch)
    arrow(c, db_x+db_w/2, height-3.45*inch-3, db_x+db_w/2, height-4.92*inch+0.95*inch+3)
    arrow(c, db_x-5, height-4.45*inch, app_x+app_w+4, height-2.72*inch)

    c.setFillColor(RED)
    c.setFont("Helvetica", 9)
    c.drawString(0.65*inch, 0.95*inch, "Public maps show aggregated counts. Community observations do not become confirmed dengue cases.")
    c.drawString(0.65*inch, 0.70*inch, "A public risk alert is issued only after authorized health personnel review it and confirm the information needed for action.")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawRightString(width-0.55*inch, 0.35*inch, "Replacement architecture - landscape page")
    c.save()
    buff.seek(0)
    DIAGRAM.write_bytes(buff.getvalue())


create_diagram_pdf()

# The original document is retained, followed by the red replacement text and diagrams.
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
writer = PdfWriter()
for source in [INPUT_PAPER, SUPPLEMENT, DIAGRAM]:
    reader = PdfReader(source)
    for page in reader.pages:
        writer.add_page(page)
writer.add_metadata({
    "/Title": "DengueWatch Capstone - Red Revision Working Copy",
    "/Subject": "Original capstone followed by simple-wording red replacement sections based on adviser suggestions",
})
with OUTPUT.open("wb") as handle:
    writer.write(handle)

print(f"Created {OUTPUT}")
print(f"Original pages: {len(PdfReader(INPUT_PAPER).pages)}")
print(f"Revision text pages: {len(PdfReader(SUPPLEMENT).pages)}")
print(f"Landscape diagram pages: {len(PdfReader(DIAGRAM).pages)}")
print(f"Final pages: {len(PdfReader(OUTPUT).pages)}")
