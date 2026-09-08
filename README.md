# Eli Lilly Clinical Trial Document Downloader

Automatically fetches and downloads **Protocol** and **Statistical Analysis Plan (SAP)** documents for all Eli Lilly-sponsored clinical trials from [ClinicalTrials.gov](https://clinicaltrials.gov), then produces an interactive HTML summary page and a CSV manifest.

---

## Quick Start

```bash
pip install requests
python download_lilly_trial_docs.py
```

To force a full re-download from scratch (ignores any prior run):

```bash
python download_lilly_trial_docs.py --force
```

### Installing via Artifactory (org compliance)

This repo includes a project-local `pip.conf` that points `pip install` at Eli Lilly's JFrog Artifactory PyPI remote repository instead of the public PyPI index. Fill in the placeholder URL in `pip.conf`, then:

```bash
export PIP_CONFIG_FILE="$(pwd)/pip.conf"   # PowerShell: $env:PIP_CONFIG_FILE = "$PWD\pip.conf"
pip install -r requirements.txt
```

This only affects `pip` invocations in the current shell session — it does not change global pip configuration on the machine.

---

## What It Does

On each run the script:

1. Queries the ClinicalTrials.gov v2 API for every trial where **Eli Lilly is the lead sponsor or a collaborator**, with a **start date on or after 1 January 2021**.
2. Pages through all results (up to 100 trials per page).
3. For each trial, checks whether a Protocol (`Prot`) or SAP (`SAP` / `Prot_SAP`) document has been posted.
4. Downloads available documents to a named folder under `lilly_trial_docs/`.
5. Writes a row to `download_manifest.csv` for every trial processed.
6. Generates `summary.html` — an interactive, filterable summary page.

---

## Output Files

| File / Folder | Description |
|---|---|
| `lilly_trial_docs/` | Root folder containing one sub-folder per trial |
| `download_manifest.csv` | Full record of every trial and document outcome |
| `summary.html` | Interactive HTML summary page (open in any browser) |

---

## Download Folder Structure

Each trial that has at least one downloadable document gets its own sub-folder named:

```
<LillyProtocolID>_<StartDate>/
```

For example:

```
lilly_trial_docs/
├── H0P-MC-NP05_14NOV2022/
│   ├── Prot_Prot_000.pdf        ← Study Protocol
│   └── SAP_SAP_001.pdf          ← Statistical Analysis Plan
│
├── J2A-MC-GZGT_09AUG2023/
│   ├── Prot_Prot_000.pdf
│   └── SAP_SAP_001.pdf
│
├── I8H-MC-BDCV_11AUG2022/
│   ├── Prot_Prot_000.pdf
│   └── SAP_SAP_001.pdf
│
└── H0P-MC-OA02_12OCT2021/
    ├── Prot_Prot_004.pdf        ← Protocol (version 4)
    └── SAP_SAP_005.pdf          ← SAP (version 5)
```

### Folder Name Format

```
<LillyProtocolID>_<DDMmmYYYY>
```

| Part | Example | Meaning |
|---|---|---|
| `LillyProtocolID` | `J2J-MC-JZLK` | Lilly internal study identifier from ClinicalTrials.gov secondary IDs |
| `DDMmmYYYY` | `12SEP2022` | Trial start date in day-month-year format |

If the Lilly ID is not available, the script falls back to the ClinicalTrials.gov `orgStudyIdInfo` identifier.

### File Name Format

```
<DocType>_<OriginalFilename>
```

| Prefix | Meaning |
|---|---|
| `Prot_` | Study Protocol document |
| `SAP_` | Statistical Analysis Plan |
| `Prot_SAP_` | Combined Protocol + SAP in a single file |

The trailing number in the original filename (e.g. `Prot_000.pdf`, `SAP_001.pdf`) is a version counter from ClinicalTrials.gov — higher numbers are later versions.

### Trials With No Documents

Trials where no Protocol or SAP has been posted **do not get a folder**. This is normal — documents are typically only uploaded after trial completion or at results posting. Active and recruiting trials rarely have posted documents.

---

## The Summary Page (`summary.html`)

Open `summary.html` in any browser after the script finishes. It provides a full, filterable overview of all trials processed.

### Page Layout

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER  — Eli Lilly, start date filter, run timestamp      │
├──────┬──────┬────────┬──────────────┬───────────┬──────────┤
│ KPI  │ KPI  │  KPI   │     KPI      │    KPI    │   KPI    │
│Total │Lead  │Collab  │Trials w/Docs │ Files DL  │ Skipped  │
├─────────────────────────────────────────────────────────────┤
│  Status Legend  (colour-coded, with trial counts)           │
├─────────────────────────────────────────────────────────────┤
│  Phase Distribution  (badges with trial counts)             │
├─────────────────────────────────────────────────────────────┤
│  [Search box]  [Phase ▼]  [Status ▼]  [Docs ▼]  [Role ▼]  │
│                                                             │
│  TABLE — one row per trial, scrollable                      │
└─────────────────────────────────────────────────────────────┘
```

---

### The KPI Banner

Six metric tiles at the top give an at-a-glance run summary:

| Tile | What it shows |
|---|---|
| **Trials Found** | Total trials returned by the API query |
| **Lilly Lead** | Trials where Eli Lilly is the primary (lead) sponsor |
| **Collab / Co-Sponsor** | Trials where another organisation leads and Lilly is a collaborator |
| **Trials With Docs** | Trials that had at least one Protocol or SAP downloaded |
| **Files Downloaded** | Total number of PDF documents saved to disk |
| **Resumed / Skipped** | Trials skipped because they were already processed in a prior run |

---

### The Trial Table

Each row represents one trial. The columns are:

| Column | What it shows |
|---|---|
| **Lilly Protocol ID** | The Lilly internal study code (e.g. `J3F-MC-EZCB`), the folder name, and a **LEAD** or **COLLAB** role badge |
| **NCT ID** | ClinicalTrials.gov identifier, linked directly to the trial's page |
| **Phase** | Study phase (Phase 1 through 4, or N/A for observational / expanded access) |
| **Protocol / Start Date** | Date the Protocol document was approved (if available), otherwise the trial start date. If a SAP date differs, it appears below in grey |
| **Status** | Trial status as a colour-coded pill badge |
| **Documents & Title** | Blue chip badges for each downloaded document type, plus the truncated trial title below |

#### Understanding the LEAD / COLLAB Badge

```
J3F-MC-EZCB  [LEAD]    ← Eli Lilly is the primary sponsor
J3Z-MC-OJAE  [COLLAB]  ← Another organisation leads; Lilly is a collaborator
```

**LEAD** (amber) means Eli Lilly registered and leads the trial.  
**COLLAB** (grey) means another institution is the lead sponsor and Lilly is listed as a collaborator or co-funder.

---

### Reading the Document Chips — Finding Protocol and SAP

The **Documents & Title** cell shows coloured chips for each document that was successfully downloaded:

```
┌───────────────────────────────────────────────────────┐
│  [Prot]  [SAP]   ← blue chips = files on disk        │
│  A Study of LY3561774 in Participants With…           │
└───────────────────────────────────────────────────────┘
```

| Chip | Colour | Meaning |
|---|---|---|
| **Prot** | Blue | Protocol PDF downloaded and saved |
| **SAP** | Blue | SAP PDF downloaded and saved |
| **Prot_SAP** | Blue | Combined Protocol + SAP PDF downloaded |
| ~~Prot~~ / ~~SAP~~ | Red (strikethrough) | Document listed on CT.gov but download failed |
| *None posted* | Grey italic | No Protocol or SAP documents are published for this trial |

**When you see a blue `Prot` or `SAP` chip, the corresponding PDF is already on your disk** in the folder shown below the Lilly ID.

Example — for a row showing `J3F-MC-EZCB` with `[Prot]` and `[SAP]` chips, the files are at:

```
lilly_trial_docs/J3F-MC-EZCB_20JUL2022/
    Prot_Prot_000.pdf
    SAP_SAP_001.pdf
```

---

### Searching and Filtering the Table

The filter bar above the table has four controls that work together in real time. **Phase, Status, Docs, and Role are multi-select checkbox dropdowns** — click one to open a checklist, and check as many values as you want. Within a single filter, checked values combine with **OR** logic (e.g. checking both `Phase 2` and `Phase 3` shows trials in either phase); across different filters, matches combine with **AND** logic. Leaving every box in a filter unchecked includes all values for that filter. The button label shows the default text (e.g. `All phases`) when nothing is checked, the checked item's label when exactly one is checked, or `N selected` when multiple are checked.

#### Free-text search box

Type any text to filter rows. The search matches against:
- Lilly Protocol ID (e.g. `J2J-MC-JZLK`)
- NCT ID (e.g. `NCT05509816`)
- Study phase (e.g. `Phase 3`)
- Lead sponsor name
- Trial title

**Examples:**

| What you type | What you find |
|---|---|
| `J2J-MC` | All trials whose Lilly ID starts with `J2J-MC` |
| `NCT05509816` | The exact trial with that NCT ID |
| `tirzepatide` | All trials mentioning tirzepatide in the title |
| `Phase 3` | All Phase 3 trials |
| `diabetes` | Trials with "diabetes" anywhere in the title |
| `ATRI` | Trials led by the Alzheimer's Therapeutic Research Institute |

#### Phase filter (multi-select dropdown)

Check one or more study phases to include. Options listed reflect only the phases actually present in the data, with counts. Phases available include Early Phase 1 through Phase 4, plus N/A for observational or expanded-access studies.

#### Status filter (multi-select dropdown)

Check one or more statuses to include:

| Status | Typical meaning |
|---|---|
| **Completed** | Trial finished; most posted documents come from here |
| **Recruiting** | Actively enrolling participants |
| **Active, Not Recruiting** | Enrolled and running but not taking new participants |
| **Not Yet Recruiting** | Approved but not yet started |
| **Terminated** | Stopped early |
| **Withdrawn** | Never started; withdrawn before enrolment |
| **Suspended** | Temporarily paused |

#### Docs filter (multi-select dropdown)

| Option | Shows |
|---|---|
| *(nothing checked)* | Every trial regardless of document availability |
| **Has documents** | Only trials with at least one downloaded file |
| **No documents** | Trials where nothing was posted or available |

Checking both boxes is equivalent to checking neither — it shows every trial.

#### Role filter (multi-select dropdown)

| Option | Shows |
|---|---|
| *(nothing checked)* | All 590+ trials |
| **Lilly as Lead only** | ~456 trials where Lilly is the primary sponsor |
| **Lilly as Collaborator only** | ~134 trials where another org leads |

Checking both boxes is equivalent to checking neither — it shows every trial.

---

### Step-by-Step: Looking Up a Specific Trial

**Scenario: You want to know if the Protocol for trial `J2J-MC-JZLK` has been downloaded.**

1. Open `summary.html` in your browser.
2. In the search box, type `J2J-MC-JZLK`.
3. The table filters to one row. Look at the last column (**Documents & Title**).
4. If you see a blue **`Prot`** chip → the Protocol PDF is on disk.  
   If you see a blue **`SAP`** chip → the SAP PDF is on disk.  
   If you see *None posted* in grey → no documents were published for this trial.
5. To open the file, navigate to the folder shown under the Lilly ID:

```
lilly_trial_docs/J2J-MC-JZLK_12SEP2022/
    Prot_Prot_000.pdf    ← open this for the Protocol
    SAP_SAP_001.pdf      ← open this for the SAP
```

**Scenario: You want all completed Phase 3 trials that have documents.**

1. Open the **Phase** dropdown and check `Phase 3`.
2. Open the **Status** dropdown and check `Completed`.
3. Open the **Docs** dropdown and check `Has documents`.
4. The table shows only completed Phase 3 trials with at least one downloaded file.

---

## The CSV Manifest (`download_manifest.csv`)

Every trial processed — whether documents were found or not — gets one or more rows in `download_manifest.csv`. This file is suitable for import into Excel, a database, or any data tool.

### Columns

| Column | Example value | Description |
|---|---|---|
| `lilly_id` | `J3F-MC-EZCB` | Lilly protocol / study identifier |
| `nct_id` | `NCT05256654` | ClinicalTrials.gov identifier |
| `title` | `A Study of LY3561774…` | Trial brief title |
| `phase` | `Phase 2` | Study phase |
| `lead_sponsor` | `Eli Lilly and Company` | Name of the lead sponsor |
| `start_date` | `2022-07-20` | Trial start date (ISO format) |
| `doc_type` | `Prot` | Document type: `Prot`, `SAP`, `Prot_SAP`, or `N/A` |
| `filename` | `Prot_000.pdf` | Original filename from ClinicalTrials.gov |
| `status` | `downloaded` | Outcome: `downloaded`, `failed`, `no_documents`, `no_protocol_or_sap`, `already_exists` |
| `local_path` | `lilly_trial_docs/…/Prot_Prot_000.pdf` | Path to the saved file (empty if not downloaded) |
| `timestamp` | `2026-06-29T05:49:51` | ISO timestamp of when this row was written |

### Status Values Explained

| `status` value | Meaning |
|---|---|
| `downloaded` | PDF was successfully saved to `local_path` |
| `already_exists` | File already existed from a prior run; not re-downloaded |
| `failed` | Download was attempted but failed (network error, etc.) |
| `no_documents` | The trial has no documents of any kind posted on CT.gov |
| `no_protocol_or_sap (available: …)` | Documents exist but none are Protocol or SAP type (e.g. only an ICF or CSR) |

---

## Resuming an Interrupted Run

If the script is interrupted mid-run, simply run it again without `--force`. It reads `download_manifest.csv` to find already-processed trials and skips them, continuing from where it left off. The **Resumed / Skipped** KPI tile on the summary page shows how many were skipped.

To restart completely from scratch and re-download everything:

```bash
python download_lilly_trial_docs.py --force
```

---

## Configuration

Edit the constants near the top of `download_lilly_trial_docs.py` to change behaviour:

| Constant | Default | Description |
|---|---|---|
| `SPONSOR` | `"Eli Lilly"` | Sponsor name to search for |
| `START_DATE_FROM` | `"2021-01-01"` | Only include trials starting on or after this date |
| `PAGE_SIZE` | `100` | Trials fetched per API page (max allowed: 100) |
| `OUTPUT_DIR` | `"lilly_trial_docs"` | Root folder for downloaded PDFs |
| `MANIFEST_FILE` | `"download_manifest.csv"` | CSV manifest filename |
| `SUMMARY_FILE` | `"summary.html"` | HTML summary filename |
| `REQUEST_DELAY` | `0.55` | Seconds to wait between API / download calls |
| `MAX_RETRIES` | `3` | Number of retry attempts on transient errors |
| `TARGET_DOC_TYPES` | `{"Prot", "SAP", "Prot_SAP"}` | Document type abbreviations to download |

---

## Document Type Reference

ClinicalTrials.gov uses short abbreviations for document types. The script targets:

| Abbreviation | Full name |
|---|---|
| `Prot` | Study Protocol |
| `SAP` | Statistical Analysis Plan |
| `Prot_SAP` | Combined Protocol and SAP (single file) |

Other types that may appear in the manifest under `no_protocol_or_sap` status:

| Abbreviation | Full name |
|---|---|
| `ICF` | Informed Consent Form |
| `CSR` | Clinical Study Report |

---

## Data Source

All data is retrieved from the **ClinicalTrials.gov v2 public API** (`https://clinicaltrials.gov/api/v2`). No API key is required. Documents are downloaded from the ClinicalTrials CDN at `https://cdn.clinicaltrials.gov/large-docs/`.

The API query uses `query.spons=Eli Lilly`, which matches trials where Eli Lilly appears as **either** the lead sponsor or a collaborator. As of June 2026 this returns approximately 590–595 trials with start date ≥ 2021-01-01.
