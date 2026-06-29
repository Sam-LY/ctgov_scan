"""
ClinicalTrials.gov — Eli Lilly Protocol & SAP Downloader (Full Run)
====================================================================
Downloads Protocol and Statistical Analysis Plan (SAP) documents for
ALL trials where Eli Lilly is lead sponsor OR collaborator/sponsor,
with start date >= 01-Jan-2021.

As of the latest query this covers ~590 trials (6 pages of 100).

Features:
  - query.spons covers Lilly as lead sponsor AND as collaborator/co-sponsor
  - Start date filter strictly >= 2021-01-01 (inclusive)
  - Study phase shown in summary page and manifest
  - Lead sponsor shown alongside Lilly protocol ID
  - Folder named using Lilly protocol ID + trial start date
    e.g.  J2J-MC-JZLK_12SEP2022/
  - Resumable: skips trials already in manifest (re-run safe)
  - Live progress bar with ETA
  - HTML summary page with filterable table  (summary.html)
  - CSV manifest                              (download_manifest.csv)

Usage:
    pip install requests
    python download_lilly_trial_docs.py

    # Force full re-download from scratch:
    python download_lilly_trial_docs.py --force

Output structure:
    lilly_trial_docs/
        J2J-MC-JZLK_12SEP2022/
            Prot_Prot_000.pdf
            SAP_SAP_001.pdf
        ...
    download_manifest.csv
    summary.html
"""

import os
import re
import csv
import sys
import time
import json
import requests
from datetime import datetime, timedelta

# ─────────────────────────── Configuration ────────────────────────────────────

SPONSOR         = "Eli Lilly"
START_DATE_FROM = "2021-01-01"      # inclusive
PAGE_SIZE       = 100               # max allowed by CT.gov API
OUTPUT_DIR      = "lilly_trial_docs"
MANIFEST_FILE   = "download_manifest.csv"
SUMMARY_FILE    = "summary.html"
REQUEST_DELAY   = 0.55              # seconds between API / download calls
MAX_RETRIES     = 3
RETRY_BACKOFF   = 2.0

TARGET_DOC_TYPES = {"Prot", "SAP", "Prot_SAP"}

CT_API_BASE = "https://clinicaltrials.gov/api/v2"
CT_CDN_BASE = "https://cdn.clinicaltrials.gov/large-docs"

FORCE_REDOWNLOAD = "--force" in sys.argv

# ──────────────────────────── Utilities ───────────────────────────────────────

MONTHS_SHORT = ["JAN","FEB","MAR","APR","MAY","JUN",
                "JUL","AUG","SEP","OCT","NOV","DEC"]
MONTHS_LONG  = ["Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"]

def format_date_folder(iso_date):
    """'2022-09-12' -> '12SEP2022'"""
    parts = iso_date.split("-")
    try:
        if len(parts) >= 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{d:02d}{MONTHS_SHORT[m-1]}{y}"
        elif len(parts) == 2:
            y, m = int(parts[0]), int(parts[1])
            return f"{MONTHS_SHORT[m-1]}{y}"
    except (ValueError, IndexError):
        pass
    return iso_date.replace("-", "")


def format_date_display(iso_date):
    """'2022-09-12' -> '12 Sep 2022'"""
    if not iso_date or iso_date in ("—", "N/A", ""):
        return iso_date or "—"
    parts = iso_date.split("-")
    try:
        if len(parts) >= 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{d:02d} {MONTHS_LONG[m-1]} {y}"
        elif len(parts) == 2:
            y, m = int(parts[0]), int(parts[1])
            return f"{MONTHS_LONG[m-1]} {y}"
    except (ValueError, IndexError):
        pass
    return iso_date


LILLY_ID_RE = re.compile(r'^[A-Z0-9]{2,4}-[A-Z0-9]{1,4}-[A-Z0-9]{3,}$')

def get_lilly_protocol_id(id_module):
    """
    Extract Lilly protocol ID from secondaryIdInfos.
    Prefers entries with domain='Eli Lilly and Company'.
    Falls back to XX-MC-XXXX pattern, then orgStudyIdInfo.
    """
    for entry in id_module.get("secondaryIdInfos", []):
        if "lilly" in entry.get("domain", "").lower():
            return entry.get("id", "")
    for entry in id_module.get("secondaryIdInfos", []):
        val = entry.get("id", "")
        if LILLY_ID_RE.match(val):
            return val
    return id_module.get("orgStudyIdInfo", {}).get("id", "UNKNOWN")


def get_phase(design_module):
    """
    Return a human-readable phase string from the designModule.
    Examples: 'Phase 1', 'Phase 2/3', 'N/A (Observational)', 'N/A'
    """
    phases = design_module.get("phases", [])
    study_type = design_module.get("studyType", "")

    if phases:
        # Normalise API values like PHASE1, PHASE2, PHASE3, PHASE4,
        # EARLY_PHASE1, NA
        readable = []
        for p in phases:
            p = p.upper()
            if p == "NA":
                readable.append("N/A")
            elif p == "EARLY_PHASE1":
                readable.append("Early Phase 1")
            elif p.startswith("PHASE"):
                num = p.replace("PHASE", "")
                readable.append(f"Phase {num}")
            else:
                readable.append(p.title())
        return "/".join(readable)

    if study_type:
        clean = study_type.replace("_", " ").title()
        if study_type.upper() == "OBSERVATIONAL":
            return "N/A (Observational)"
        if study_type.upper() == "EXPANDED_ACCESS":
            return "N/A (Expanded Access)"
        return f"N/A ({clean})"

    return "N/A"


def build_folder_name(lilly_id, start_date_iso):
    date_label = format_date_folder(start_date_iso) if start_date_iso not in ("N/A", "") else "NODATE"
    safe_id    = re.sub(r'[/\\:\s]', '_', lilly_id)
    return f"{safe_id}_{date_label}"


def build_doc_url(nct_id, filename):
    suffix = nct_id.replace("NCT", "")[-2:]
    return f"{CT_CDN_BASE}/{suffix}/{nct_id}/{filename}"


def format_eta(seconds):
    if seconds < 0:
        return "calculating..."
    td  = timedelta(seconds=int(seconds))
    h, rem = divmod(td.seconds, 3600)
    m, s   = divmod(rem, 60)
    if td.days > 0:
        return f"{td.days}d {h:02d}h {m:02d}m"
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def print_progress(current, total, start_ts, extra=""):
    pct    = current / total * 100 if total else 0
    elapsed = time.time() - start_ts
    rate   = current / elapsed if elapsed > 0 and current > 0 else 0
    eta    = (total - current) / rate if rate > 0 else -1
    filled = int(30 * current / total) if total else 0
    bar    = "█" * filled + "░" * (30 - filled)
    print(f"\r  [{bar}] {current}/{total} ({pct:.1f}%)  ETA: {format_eta(eta)}  {extra}",
          end="", flush=True)

# ──────────────────────────── Session & Retry ─────────────────────────────────

def get_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "TrialDocDownloader/1.0 (research use)"})
    return s


def request_with_retry(session, url, params=None, stream=False, timeout=60):
    backoff = RETRY_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, stream=stream, timeout=timeout)
            if resp.status_code == 429:
                wait = backoff * attempt
                print(f"\n  [RATE LIMIT] Waiting {wait:.0f}s (attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES:
                raise
            print(f"\n  [TIMEOUT] Retry {attempt}/{MAX_RETRIES}...")
            time.sleep(backoff * attempt)
        except requests.exceptions.HTTPError as e:
            if resp.status_code in (500, 502, 503, 504) and attempt < MAX_RETRIES:
                print(f"\n  [HTTP {resp.status_code}] Retry {attempt}/{MAX_RETRIES}...")
                time.sleep(backoff * attempt)
            else:
                raise
        except requests.exceptions.ConnectionError:
            if attempt == MAX_RETRIES:
                raise
            print(f"\n  [CONN ERROR] Retry {attempt}/{MAX_RETRIES}...")
            time.sleep(backoff * attempt)
    return None

# ──────────────────────────── Resumption ──────────────────────────────────────

def load_manifest_nct_ids():
    """Return NCT IDs already recorded in the manifest (for resume)."""
    seen = set()
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                nct = row.get("nct_id", "")
                if nct:
                    seen.add(nct)
    return seen

# ──────────────────────────── API: Fetch All Trials ───────────────────────────

def fetch_all_trials(session):
    """
    Page through ALL CT.gov results for Eli Lilly (sponsor or collaborator)
    with start date >= START_DATE_FROM.

    Uses query.spons which matches:
      - Trials where Lilly is the lead sponsor
      - Trials where Lilly is a collaborator/co-sponsor
    """
    print(f"\n{'='*66}")
    print(f"  Fetching ALL Eli Lilly trials from ClinicalTrials.gov")
    print(f"  Search         : query.spons = \"{SPONSOR}\"")
    print(f"                   (matches lead sponsor AND collaborator)")
    print(f"  Start date >=  : {START_DATE_FROM}  (inclusive)")
    print(f"  Page size      : {PAGE_SIZE} per page")
    print(f"{'='*66}\n")

    url    = f"{CT_API_BASE}/studies"
    params = {
        "query.spons":     SPONSOR,
        "filter.advanced": f"AREA[StartDate]RANGE[{START_DATE_FROM},MAX]",
        "pageSize":        PAGE_SIZE,
        "format":          "json",
        "countTotal":      "true",
    }

    print("  Fetching page 1 / getting total count...", flush=True)
    resp       = request_with_retry(session, url, params=params, timeout=30)
    data       = resp.json()
    total      = data.get("totalCount", "?")
    studies    = list(data.get("studies", []))
    page_token = data.get("nextPageToken")
    print(f"  Total trials matching query: {total}")
    print(f"  Fetching remaining pages...\n")

    fetch_start = time.time()
    page_num    = 1

    while page_token:
        page_num += 1
        print_progress(len(studies), total if isinstance(total, int) else len(studies),
                       fetch_start, f"page {page_num}")
        time.sleep(REQUEST_DELAY)
        p2 = {**params, "pageToken": page_token}
        del p2["countTotal"]
        try:
            resp       = request_with_retry(session, url, params=p2, timeout=30)
            data       = resp.json()
            studies   += data.get("studies", [])
            page_token = data.get("nextPageToken")
        except Exception as e:
            print(f"\n  [ERROR] Page {page_num} failed: {e}")
            print(f"  Continuing with {len(studies)} records collected so far.")
            break

    print(f"\n\n  Collected {len(studies)} trial records.\n")
    return studies

# ──────────────────────────── Trial Processor ─────────────────────────────────

def process_trial(session, study, manifest_writer, already_done):
    """
    Download Protocol + SAP for one study.
    Returns a summary dict for the HTML report (or None on hard error).
    """
    proto    = study.get("protocolSection", {})
    id_mod   = proto.get("identificationModule", {})
    stat_mod = proto.get("statusModule", {})
    design_mod = proto.get("designModule", {})
    sc_mod   = proto.get("sponsorCollaboratorsModule", {})

    nct_id      = id_mod.get("nctId", "")
    lilly_id    = get_lilly_protocol_id(id_mod)
    title       = id_mod.get("briefTitle", "N/A")
    start_date  = stat_mod.get("startDateStruct", {}).get("date", "N/A")
    status      = stat_mod.get("overallStatus", "N/A")
    phase       = get_phase(design_mod)
    lead_sponsor = sc_mod.get("leadSponsor", {}).get("name", "N/A")

    folder_name = build_folder_name(lilly_id, start_date)
    trial_dir   = os.path.join(OUTPUT_DIR, folder_name)

    summary = {
        "lilly_id":    lilly_id,
        "nct_id":      nct_id,
        "title":       title,
        "start_date":  start_date,
        "status":      status,
        "phase":       phase,
        "lead_sponsor": lead_sponsor,
        "prot_date":   "—",
        "sap_date":    "—",
        "folder":      folder_name,
        "docs":        [],
        "skipped":     False,
    }

    # Resume: skip if already processed in a prior run
    if not FORCE_REDOWNLOAD and nct_id in already_done:
        summary["skipped"] = True
        return summary

    # documentSection is in the full study record (no field filter used)
    docs = (
        study.get("documentSection", {})
             .get("largeDocumentModule", {})
             .get("largeDocs", [])
    )

    def _write_manifest(doc_type, filename, status_val, local_path=""):
        manifest_writer.writerow({
            "lilly_id":    lilly_id,
            "nct_id":      nct_id,
            "title":       title,
            "phase":       phase,
            "lead_sponsor": lead_sponsor,
            "start_date":  start_date,
            "doc_type":    doc_type,
            "filename":    filename,
            "status":      status_val,
            "local_path":  local_path,
            "timestamp":   datetime.now().isoformat(),
        })

    if not docs:
        _write_manifest("N/A", "N/A", "no_documents")
        return summary

    # Capture protocol / SAP dates for summary
    for doc in docs:
        abbrev   = doc.get("typeAbbrev", "")
        doc_date = doc.get("date", "")
        if abbrev in ("Prot", "Prot_SAP") and doc_date and summary["prot_date"] == "—":
            summary["prot_date"] = doc_date
        if abbrev in ("SAP", "Prot_SAP") and doc_date and summary["sap_date"] == "—":
            summary["sap_date"] = doc_date

    target_docs = [d for d in docs if d.get("typeAbbrev") in TARGET_DOC_TYPES]

    if not target_docs:
        all_types = sorted({d.get("typeAbbrev", "?") for d in docs})
        _write_manifest("N/A", "N/A", f"no_protocol_or_sap (available: {all_types})")
        return summary

    os.makedirs(trial_dir, exist_ok=True)

    for doc in target_docs:
        doc_type   = doc.get("typeAbbrev", "UNKNOWN")
        filename   = doc.get("filename", "")
        if not filename:
            continue

        local_path = os.path.join(trial_dir, f"{doc_type}_{filename}")

        # Skip file if it already exists and is non-empty
        if not FORCE_REDOWNLOAD and os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            summary["docs"].append({"type": doc_type, "filename": filename,
                                    "local_path": local_path, "ok": True})
            _write_manifest(doc_type, filename, "already_exists", local_path)
            continue

        ok = _download(session, nct_id, filename, local_path)
        time.sleep(REQUEST_DELAY)

        summary["docs"].append({"type": doc_type, "filename": filename,
                                 "local_path": local_path if ok else "", "ok": ok})
        _write_manifest(doc_type, filename, "downloaded" if ok else "failed",
                        local_path if ok else "")

    return summary


def _download(session, nct_id, filename, dest_path):
    """Stream-download a PDF from the CDN. Returns True on success."""
    url = build_doc_url(nct_id, filename)
    try:
        resp = request_with_retry(session, url, stream=True, timeout=120)
        if resp is None:
            return False
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"\n    [ERROR] {os.path.basename(url)}: {e}")
        return False

# ────────────────────────── HTML Summary Report ───────────────────────────────

STATUS_COLORS = {
    "COMPLETED":             "#16a34a",
    "RECRUITING":            "#2563eb",
    "ACTIVE_NOT_RECRUITING": "#d97706",
    "TERMINATED":            "#dc2626",
    "WITHDRAWN":             "#64748b",
    "NOT_YET_RECRUITING":    "#7c3aed",
    "SUSPENDED":             "#ea580c",
    "UNKNOWN":               "#94a3b8",
}

PHASE_COLORS = {
    "Phase 1":       "#0ea5e9",
    "Phase 2":       "#8b5cf6",
    "Phase 3":       "#ec4899",
    "Phase 4":       "#f59e0b",
    "Early Phase 1": "#06b6d4",
    "Phase 1/2":     "#6366f1",
    "Phase 2/3":     "#a855f7",
}

def phase_badge(phase):
    color = PHASE_COLORS.get(phase, "#94a3b8")
    return (f'<span style="background:{color}1a;color:{color};padding:2px 9px;'
            f'border-radius:6px;font-size:0.70rem;font-weight:700;'
            f'white-space:nowrap;border:1px solid {color}40">{phase}</span>')


def status_badge(status):
    color = STATUS_COLORS.get(status, "#94a3b8")
    label = status.replace("_", " ").title()
    return (f'<span style="background:{color};color:#fff;padding:3px 10px;'
            f'border-radius:999px;font-size:0.70rem;font-weight:700;'
            f'letter-spacing:0.04em;white-space:nowrap">{label}</span>')


def doc_chips(summary):
    chips = []
    for d in summary["docs"]:
        if d["ok"]:
            chips.append(
                f'<span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;'
                f'border-radius:999px;font-size:0.70rem;font-weight:700;margin-right:3px">'
                f'{d["type"]}</span>')
        else:
            chips.append(
                f'<span style="background:#fee2e2;color:#b91c1c;padding:2px 8px;'
                f'border-radius:999px;font-size:0.70rem;font-weight:700;margin-right:3px;'
                f'text-decoration:line-through">{d["type"]}</span>')
    if not chips:
        return '<span style="color:#cbd5e1;font-size:0.73rem;font-style:italic">None posted</span>'
    return "".join(chips)


def write_summary_html(summaries, run_ts, total_fetched):
    real  = [s for s in summaries if not s.get("skipped")]
    total = len(summaries)
    with_docs   = sum(1 for s in real if any(d["ok"] for d in s["docs"]))
    total_files = sum(sum(1 for d in s["docs"] if d["ok"]) for s in real)
    skipped     = sum(1 for s in summaries if s.get("skipped"))
    lilly_lead  = sum(1 for s in summaries
                      if "lilly" in s.get("lead_sponsor", "").lower())
    collab_only = total - lilly_lead

    # Status & phase breakdown counts
    status_counts = {}
    phase_counts  = {}
    for s in summaries:
        status_counts[s["status"]] = status_counts.get(s["status"], 0) + 1
        phase_counts[s["phase"]]   = phase_counts.get(s["phase"], 0) + 1

    # ── Table rows ──────────────────────────────────────────────────────────
    rows_html = ""
    for i, s in enumerate(summaries, 1):
        prot_raw = s["prot_date"] if s["prot_date"] != "—" else s["start_date"]
        prot_display = format_date_display(prot_raw)
        sap_display  = format_date_display(s["sap_date"])

        ct_link = (f'<a href="https://clinicaltrials.gov/study/{s["nct_id"]}" '
                   f'target="_blank" style="color:#2563eb;text-decoration:none;'
                   f'font-size:0.80rem;font-family:monospace;font-weight:600">'
                   f'{s["nct_id"]}</a>')

        row_bg      = "#f8fafc" if i % 2 == 0 else "#ffffff"
        title_trunc = s["title"][:65] + "…" if len(s["title"]) > 65 else s["title"]
        skip_note   = (' <span style="font-size:0.62rem;color:#94a3b8">(resumed)</span>'
                       if s.get("skipped") else "")

        # Indicate if Lilly is lead vs collaborator
        is_lead = "lilly" in s.get("lead_sponsor", "").lower()
        lead_badge = (
            '<span style="font-size:0.65rem;background:#fef3c7;color:#92400e;'
            'padding:1px 5px;border-radius:4px;font-weight:600">LEAD</span>'
            if is_lead else
            '<span style="font-size:0.65rem;background:#f3f4f6;color:#6b7280;'
            'padding:1px 5px;border-radius:4px;font-weight:600">COLLAB</span>'
        )

        rows_html += f"""
        <tr style="background:{row_bg};border-bottom:1px solid #e2e8f0" class="tr">
          <td style="padding:9px 12px">
            <div style="display:flex;align-items:center;gap:5px">
              <span style="font-weight:700;color:#0f172a;font-family:monospace;
                           font-size:0.82rem">{s["lilly_id"]}</span>{skip_note}
              {lead_badge}
            </div>
            <div style="font-size:0.67rem;color:#94a3b8;margin-top:2px;
                        font-family:monospace">{s["folder"]}</div>
          </td>
          <td style="padding:9px 12px">{ct_link}</td>
          <td style="padding:9px 8px;text-align:center">{phase_badge(s["phase"])}</td>
          <td style="padding:9px 12px;font-size:0.80rem;color:#334155">
            <div>{prot_display}</div>
            {"<div style='font-size:0.67rem;color:#94a3b8;margin-top:1px'>SAP: " + sap_display + "</div>" if s["sap_date"] != "—" else ""}
          </td>
          <td style="padding:9px 9px;text-align:center">{status_badge(s["status"])}</td>
          <td style="padding:9px 12px">
            <div>{doc_chips(s)}</div>
            <div style="font-size:0.67rem;color:#94a3b8;margin-top:2px;max-width:260px;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
                 title="{s['title']}">{title_trunc}</div>
          </td>
        </tr>"""

    # ── Status legend ────────────────────────────────────────────────────────
    status_legend = "".join(
        f'<span style="display:flex;align-items:center;gap:4px">'
        f'<span style="width:9px;height:9px;border-radius:50%;background:{c};'
        f'display:inline-block"></span>'
        f'<span style="font-size:0.72rem;color:#475569">'
        f'{st.replace("_"," ").title()} ({status_counts.get(st, 0)})</span></span>'
        for st, c in STATUS_COLORS.items()
        if status_counts.get(st, 0) > 0
    )

    # ── Phase legend ─────────────────────────────────────────────────────────
    sorted_phases = sorted(phase_counts.items(),
                           key=lambda x: (x[0] == "N/A", x[0]))
    phase_legend = "".join(
        f'<span style="display:flex;align-items:center;gap:4px">'
        f'{phase_badge(ph)}'
        f'<span style="font-size:0.72rem;color:#475569">({cnt})</span></span>'
        for ph, cnt in sorted_phases
    )

    # ── Phase filter options ─────────────────────────────────────────────────
    phase_opts = "".join(
        f'<option value="{ph}">{ph} ({cnt})</option>'
        for ph, cnt in sorted_phases
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Eli Lilly — Trial Document Download Summary</title>
  <style>
    *, *::before, *::after {{ box-sizing:border-box;margin:0;padding:0 }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
            background:#f1f5f9;color:#1e293b;min-height:100vh }}
    .header {{ background:linear-gradient(135deg,#c8102e 0%,#8b0c20 100%);color:#fff;
               padding:28px 44px 24px;box-shadow:0 4px 20px rgba(0,0,0,0.20) }}
    .header h1 {{ font-size:1.32rem;font-weight:800;letter-spacing:-0.02em }}
    .meta {{ font-size:0.79rem;opacity:0.83;margin-top:8px;display:flex;
             gap:16px;flex-wrap:wrap;align-items:center }}
    .kpi-row {{ display:flex;gap:14px;padding:20px 44px;flex-wrap:wrap }}
    .kpi {{ background:#fff;border-radius:12px;padding:15px 20px;min-width:130px;flex:1;
            box-shadow:0 1px 4px rgba(0,0,0,0.08) }}
    .kpi.red  {{ border-top:4px solid #c8102e }}
    .kpi.blue {{ border-top:4px solid #2563eb }}
    .kpi.green{{ border-top:4px solid #16a34a }}
    .kpi.amber{{ border-top:4px solid #d97706 }}
    .kpi.purple{{border-top:4px solid #7c3aed }}
    .kpi.slate{{ border-top:4px solid #64748b }}
    .kpi .val {{ font-size:1.9rem;font-weight:900;line-height:1 }}
    .kpi.red  .val {{ color:#c8102e }}
    .kpi.blue .val {{ color:#2563eb }}
    .kpi.green .val{{ color:#16a34a }}
    .kpi.amber .val{{ color:#d97706 }}
    .kpi.purple .val{{color:#7c3aed }}
    .kpi.slate .val{{ color:#64748b }}
    .kpi .lbl {{ font-size:0.68rem;color:#64748b;margin-top:3px;text-transform:uppercase;
                letter-spacing:0.07em;font-weight:700 }}
    .section {{ margin:0 44px 30px }}
    .section-title {{ font-size:0.74rem;font-weight:700;text-transform:uppercase;
                      letter-spacing:0.08em;color:#64748b;margin-bottom:10px;
                      display:flex;align-items:center;gap:7px }}
    .legend {{ display:flex;gap:10px;flex-wrap:wrap;background:#fff;padding:12px 16px;
               border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,0.06) }}
    .filters {{ display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap }}
    .filters input, .filters select {{
      padding:7px 13px;border:1.5px solid #e2e8f0;border-radius:8px;
      font-size:0.82rem;outline:none;background:#fff }}
    .filters input {{ flex:2;min-width:200px }}
    .filters input:focus, .filters select:focus {{ border-color:#c8102e }}
    .table-wrap {{ background:#fff;border-radius:14px;overflow:hidden;
                   box-shadow:0 1px 8px rgba(0,0,0,0.09) }}
    .table-hdr {{ padding:13px 18px 10px;border-bottom:2px solid #f1f5f9;
                  display:flex;justify-content:space-between;align-items:center }}
    .table-hdr .tit {{ font-weight:700;font-size:0.90rem;color:#0f172a }}
    .table-hdr .cnt {{ font-size:0.75rem;color:#94a3b8 }}
    table {{ width:100%;border-collapse:collapse }}
    thead th {{ background:#f8fafc;padding:8px 12px;text-align:left;
                font-size:0.67rem;text-transform:uppercase;letter-spacing:0.08em;
                color:#64748b;font-weight:700;border-bottom:2px solid #e2e8f0;
                position:sticky;top:0;z-index:10 }}
    .tr:hover {{ background:#eff6ff !important;transition:background 0.12s }}
    .hidden {{ display:none }}
    .footer {{ text-align:center;padding:18px;font-size:0.72rem;color:#94a3b8;
               border-top:1px solid #e2e8f0;margin-top:6px }}
    .footer code {{ background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:0.76rem }}
    .note {{ font-size:0.75rem;color:#64748b;background:#fafafa;
             border-left:3px solid #c8102e;padding:8px 14px;border-radius:0 6px 6px 0;
             margin-top:8px }}
  </style>
</head>
<body>

<div class="header">
  <div style="display:flex;align-items:center;gap:14px;margin-bottom:10px">
    <div style="width:42px;height:42px;background:rgba(255,255,255,0.18);border-radius:10px;
                display:flex;align-items:center;justify-content:center;font-size:1.4rem">🧬</div>
    <h1>Eli Lilly — Clinical Trial Document Download Summary</h1>
  </div>
  <div class="meta">
    <span>🏢 <strong>Eli Lilly</strong> (lead sponsor or collaborator)</span>
    <span>📅 Start date ≥ <strong>{START_DATE_FROM}</strong></span>
    <span>🕐 <strong>{run_ts}</strong></span>
    <span>📁 <code style="background:rgba(255,255,255,0.15);padding:1px 6px;
         border-radius:4px;font-size:0.78rem">{OUTPUT_DIR}/</code></span>
  </div>
</div>

<div class="kpi-row">
  <div class="kpi red">  <div class="val">{total_fetched}</div><div class="lbl">Trials Found</div></div>
  <div class="kpi blue"> <div class="val">{lilly_lead}</div>  <div class="lbl">Lilly Lead</div></div>
  <div class="kpi slate"><div class="val">{collab_only}</div> <div class="lbl">Collab / Co-Sponsor</div></div>
  <div class="kpi green"><div class="val">{with_docs}</div>   <div class="lbl">Trials With Docs</div></div>
  <div class="kpi amber"><div class="val">{total_files}</div> <div class="lbl">Files Downloaded</div></div>
  <div class="kpi purple"><div class="val">{skipped}</div>   <div class="lbl">Resumed / Skipped</div></div>
</div>

<div class="section">
  <div class="section-title">⬤ Trial Status</div>
  <div class="legend">{status_legend}</div>
</div>

<div class="section">
  <div class="section-title">🔬 Study Phase Distribution</div>
  <div class="legend">{phase_legend}</div>
</div>

<div class="section">
  <div class="section-title">📋 Trial Document Index</div>

  <div class="filters">
    <input  type="text"   id="searchBox"    placeholder="Filter by Lilly ID, NCT ID, phase, lead sponsor, or title..."
            oninput="filterTable()">
    <select id="phaseFilter"  onchange="filterTable()">
      <option value="">All phases</option>
      {phase_opts}
    </select>
    <select id="statusFilter" onchange="filterTable()">
      <option value="">All statuses</option>
      {''.join(f'<option value="{s}">{s.replace("_"," ").title()}</option>'
               for s in STATUS_COLORS if status_counts.get(s,0)>0)}
    </select>
    <select id="docsFilter"   onchange="filterTable()">
      <option value="">All trials</option>
      <option value="has_docs">Has documents</option>
      <option value="no_docs">No documents</option>
    </select>
    <select id="roleFilter"   onchange="filterTable()">
      <option value="">Lead + Collaborator</option>
      <option value="lead">Lilly as Lead only</option>
      <option value="collab">Lilly as Collaborator only</option>
    </select>
  </div>

  <div class="note">
    <strong>LEAD</strong> = Eli Lilly is the lead sponsor &nbsp;·&nbsp;
    <strong>COLLAB</strong> = Eli Lilly is a collaborator/co-sponsor on another org's trial
  </div>

  <div class="table-wrap" style="margin-top:12px">
    <div class="table-hdr">
      <span class="tit">All Trials</span>
      <span class="cnt" id="rowCount">{total} records &nbsp;·&nbsp; {total_files} documents downloaded</span>
    </div>
    <div style="max-height:74vh;overflow-y:auto">
      <table id="mainTable">
        <thead>
          <tr>
            <th>Lilly Protocol ID</th>
            <th>NCT ID</th>
            <th style="text-align:center">Phase</th>
            <th>Protocol / Start Date</th>
            <th style="text-align:center">Status</th>
            <th>Documents &amp; Title</th>
          </tr>
        </thead>
        <tbody id="tableBody">
          {rows_html}
        </tbody>
      </table>
    </div>
  </div>
</div>

<div class="footer">
  Data sourced from <strong>ClinicalTrials.gov</strong> public API v2 &nbsp;·&nbsp;
  Files in <code>{OUTPUT_DIR}/</code> &nbsp;·&nbsp;
  Manifest: <code>{MANIFEST_FILE}</code>
</div>

<script>
function filterTable() {{
  const q      = document.getElementById('searchBox').value.toLowerCase();
  const phase  = document.getElementById('phaseFilter').value;
  const status = document.getElementById('statusFilter').value;
  const docs   = document.getElementById('docsFilter').value;
  const role   = document.getElementById('roleFilter').value;
  const rows   = document.querySelectorAll('#tableBody tr');
  let visible  = 0;

  rows.forEach(row => {{
    const text    = row.innerText.toLowerCase();

    // Phase: text of first badge in col 3 (index 2)
    const phaseCell = row.cells[2];
    const phaseText = phaseCell ? phaseCell.innerText.trim() : '';

    // Status: text of badge in col 5 (index 4)
    const statCell  = row.cells[4];
    const statText  = statCell ? statCell.innerText.trim().toUpperCase().replace(/ /g,'_') : '';

    // Has docs: blue chip present
    const hasDoc  = row.querySelector('span[style*="#1d4ed8"]') !== null;

    // Role: LEAD or COLLAB badge
    const hasLead  = row.querySelector('span[style*="LEAD"]') !== null ||
                     (row.innerText.indexOf('LEAD') > -1 &&
                      row.querySelector('span[style*="#92400e"]') !== null);
    const isLead   = row.querySelector('span[style*="#92400e"]') !== null;

    const matchQ   = !q      || text.includes(q);
    const matchPh  = !phase  || phaseText === phase;
    const matchSt  = !status || statText  === status;
    const matchDoc = !docs
                     || (docs === 'has_docs' && hasDoc)
                     || (docs === 'no_docs'  && !hasDoc);
    const matchRole= !role
                     || (role === 'lead'   && isLead)
                     || (role === 'collab' && !isLead);

    const show = matchQ && matchPh && matchSt && matchDoc && matchRole;
    row.classList.toggle('hidden', !show);
    if (show) visible++;
  }});

  document.getElementById('rowCount').textContent =
    visible + ' record' + (visible !== 1 ? 's' : '') + ' shown';
}}
</script>
</body>
</html>"""

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML summary  -> {SUMMARY_FILE}")

# ─────────────────────────────── Entry Point ──────────────────────────────────

def main():
    run_ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_start = time.time()

    print(f"\n  ClinicalTrials.gov -- Eli Lilly Full Protocol & SAP Downloader")
    print(f"  Run started : {run_ts}")
    print(f"  Mode        : {'FORCE (re-downloading everything)' if FORCE_REDOWNLOAD else 'RESUMABLE (skips already-completed trials)'}")
    print()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = get_session()

    # Load already-processed NCT IDs (resume support)
    already_done = set() if FORCE_REDOWNLOAD else load_manifest_nct_ids()
    if already_done:
        print(f"  Resuming: {len(already_done)} trials already in manifest — will skip.\n")

    # Step 1: Fetch all study records
    studies = fetch_all_trials(session)
    total_fetched = len(studies)
    if not studies:
        print("  No trials found. Exiting.")
        return

    # Step 2: Open manifest (write/append) and process every trial
    manifest_fields = ["lilly_id", "nct_id", "title", "phase", "lead_sponsor",
                       "start_date", "doc_type", "filename",
                       "status", "local_path", "timestamp"]
    write_header = not os.path.exists(MANIFEST_FILE) or FORCE_REDOWNLOAD
    manifest_mode = "w" if (write_header or FORCE_REDOWNLOAD) else "a"

    summaries  = []
    downloaded = 0
    failed     = 0
    no_docs    = 0
    skipped    = 0
    proc_start = time.time()

    print(f"Processing {total_fetched} trials...\n")

    with open(MANIFEST_FILE, manifest_mode, newline="", encoding="utf-8") as mf:
        writer = csv.DictWriter(mf, fieldnames=manifest_fields)
        if write_header or FORCE_REDOWNLOAD:
            writer.writeheader()

        for i, study in enumerate(studies, 1):
            proto  = study.get("protocolSection", {})
            id_mod = proto.get("identificationModule", {})
            nct_id   = id_mod.get("nctId", "")
            lilly_id = get_lilly_protocol_id(id_mod)

            print_progress(i - 1, total_fetched, proc_start,
                           f"[{nct_id} | {lilly_id}]")

            summary = process_trial(session, study, writer, already_done)
            mf.flush()

            if summary:
                summaries.append(summary)
                if summary.get("skipped"):
                    skipped += 1
                else:
                    downloaded += sum(1 for d in summary["docs"] if d["ok"])
                    failed     += sum(1 for d in summary["docs"] if not d["ok"])
                    if not summary["docs"]:
                        no_docs += 1

    print_progress(total_fetched, total_fetched, proc_start, "done")
    print("\n")

    # Step 3: Write HTML summary
    print("Writing output files...")
    write_summary_html(summaries, run_ts, total_fetched)

    # Step 4: Final console summary
    elapsed = time.time() - run_start
    lilly_lead  = sum(1 for s in summaries if "lilly" in s.get("lead_sponsor", "").lower())
    print(f"\n{'='*66}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*66}")
    print(f"  Total trials found     : {total_fetched}")
    print(f"  Lilly as lead sponsor  : {lilly_lead}")
    print(f"  Lilly as collaborator  : {total_fetched - lilly_lead}")
    print(f"  Trials skipped (resume): {skipped}")
    print(f"  Trials with no docs    : {no_docs}")
    print(f"  Documents downloaded   : {downloaded}")
    print(f"  Downloads failed       : {failed}")
    print(f"  Elapsed time           : {format_eta(elapsed)}")
    print(f"  Output directory       : ./{OUTPUT_DIR}/")
    print(f"  CSV manifest           : ./{MANIFEST_FILE}")
    print(f"  HTML summary           : ./{SUMMARY_FILE}")
    if failed:
        print(f"\n  TIP: Re-run with --force to retry failed downloads.")
    print(f"{'='*66}\n")


if __name__ == "__main__":
    main()
