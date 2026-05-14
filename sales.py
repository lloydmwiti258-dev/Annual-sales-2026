"""
SALES.PY — Annual Bags Sold 2026 Analytics
============================================
Sheet layout expected:
  Row 1, Col F+  : Month names  (e.g. Jan, Feb, … Dec)
  Row 2, Col F+  : Location/shop names  (dynamic; one column each; includes a "Total" column)
  Col A           : Bag category
  Col B           : Recognised colour
  Col C           : (reserved / description)
  Col D           : Bag type
  Col E           : (reserved / SKU etc.)
  Data rows start : Row 3 onwards
"""

import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
import os
from collections import defaultdict

# ══════════════════════════════════════════════════════════════════════════════
# ❶  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
JSON_FILE_PATH = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'credentials.json')
SHEET_ID       = '1DYkR0P4W1XUd7m4SmNWjqPimE0fbDq3P4d2yvsL48Wo'
SHEET_NAME     = 'Annual_2026'
WORKSHEET_NAME = 'ANNUAL_BAGS_SOLD_2026'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# ── Region colour palette ──────────────────────────────────────────────────
REGION_COLORS = {
    'Nairobi CBD':      '#3498db',   # Blue
    'Coastal Region':   '#e74c3c',   # Red
    'Western & Nyanza': '#2ecc71',   # Green
    'Central Region':   '#f39c12',   # Orange
    'Rift Valley':      '#9b59b6',   # Purple
    'Diaspora':         '#1abc9c',   # Turquoise
    'Reject Region':    '#7f8c8d',   # Gray
    'Online':           '#3498db',   # Blue
}

# ── Shop → Region mapping ──────────────────────────────────────────────────
SHOP_REGION_MAP = {
    'Hazina':    'Nairobi CBD',
    'Hilton':    'Nairobi CBD',
    'Starmall':  'Nairobi CBD',
    'Ktda':      'Nairobi CBD',
    'Mombasa':   'Coastal Region',
    'Kakamega':  'Western & Nyanza',
    'Kisumu':    'Western & Nyanza',
    'Kisii':     'Western & Nyanza',
    'Busia':     'Western & Nyanza',
    'Meru':      'Central Region',
    'Nanyuki':   'Central Region',
    'Thika':     'Central Region',
    'Eldoret':   'Rift Valley',
    'Nakuru':    'Rift Valley',
    'Kitengela': 'Rift Valley',
    'Sinza':     'Diaspora',
    'Tanzania':  'Diaspora',
    'Uganda':    'Diaspora',
    'Rejects':   'Reject Region',
    'Website':   'Online',
    'Rongai':    'Rift Valley',
}

SHOP_REGION_MAP_LOWER = {loc.strip().lower(): region for loc, region in SHOP_REGION_MAP.items()}

def get_region_for_location(location: str) -> str:
    return SHOP_REGION_MAP_LOWER.get(location.strip().lower(), 'Unknown')


# ══════════════════════════════════════════════════════════════════════════════
# ❷  AUTHENTICATION & RAW FETCH
# ══════════════════════════════════════════════════════════════════════════════
def get_worksheet():
    """Authenticate and return the target gspread Worksheet object."""
    # Try environment variable first (for Render/Production)
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    
    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            print("OK  Authenticated via GOOGLE_CREDENTIALS env var")
        except Exception as e:
            print(f"Error parsing GOOGLE_CREDENTIALS: {e}")
            creds = Credentials.from_service_account_file(JSON_FILE_PATH, scopes=SCOPES)
    else:
        # Fallback to local file
        if not os.path.exists(JSON_FILE_PATH):
            print(f"[ERROR] Credentials file not found at {JSON_FILE_PATH}")
            raise FileNotFoundError(f"Credentials not found. Set GOOGLE_CREDENTIALS or provide {JSON_FILE_PATH}")
        creds = Credentials.from_service_account_file(JSON_FILE_PATH, scopes=SCOPES)
        print(f"OK  Authenticated via {JSON_FILE_PATH}")

    client    = gspread.authorize(creds)
    sheet     = client.open_by_key(SHEET_ID)
    ws        = sheet.worksheet(WORKSHEET_NAME)
    print(f"OK  Connected  ->  '{SHEET_NAME}' / '{WORKSHEET_NAME}'")
    return ws


def fetch_raw(ws) -> list[list]:
    """Return all values as a 2-D list (no header inference)."""
    return ws.get_all_values()


# ══════════════════════════════════════════════════════════════════════════════
# ❸  HEADER PARSING  (dynamic — handles any number of months / locations)
# ══════════════════════════════════════════════════════════════════════════════
def parse_headers(raw: list[list]) -> dict:
    """
    Analyse rows 1 & 2 (index 0 & 1) to build a structured header map.

    Returns
    -------
    {
        'months'    : ['Jan','Feb', …],
        'locations' : ['Hazina','Hilton', …],   # excludes 'Total' sentinel
        'col_index' : {(month, location): col_idx, …}
        'total_cols': {month: col_idx, …}        # column for the monthly total
    }
    """
    month_row    = raw[0]     # row 1
    location_row = raw[1]     # row 2

    months_seen   = []
    col_index     = {}        # (month, location) → col_idx
    total_cols    = {}        # month → col_idx  (the "Total" column)
    current_month = None

    # Columns A-E (0-4) are metadata; sales data starts at F (index 5)
    for ci in range(5, len(month_row)):
        month_cell    = month_row[ci].strip()
        location_cell = location_row[ci].strip()

        # Carry forward the month label (merged cells arrive as blank after first)
        if month_cell:
            current_month = month_cell
            if current_month not in months_seen:
                months_seen.append(current_month)

        if not current_month:
            continue

        # Exclude any month-level summary columns labeled Total
        if location_cell and 'total' in location_cell.lower():
            if current_month not in total_cols:
                total_cols[current_month] = ci
        elif location_cell:
            if (current_month, location_cell) not in col_index:
                col_index[(current_month, location_cell)] = ci

    # All unique locations in order of first appearance
    locations = list(dict.fromkeys(
        loc for (_, loc) in col_index.keys()
    ))

    print(f"Months    : {months_seen}")
    print(f"Locations : {locations}")

    return {
        'months':    months_seen,
        'locations': locations,
        'col_index': col_index,
        'total_cols': total_cols,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ❹  BUILD LONG-FORMAT DATAFRAME
# ══════════════════════════════════════════════════════════════════════════════
def build_dataframe(raw: list[list], headers: dict) -> pd.DataFrame:
    """
    Melt the wide sheet into a tidy long-format DataFrame by parsing individual rows.
    """
    rows = []
    data_rows = raw[2:]
    
    for r in data_rows:
        # Pad short rows
        while len(r) < max(headers['col_index'].values(), default=0) + 1:
            r.append('')

        category     = r[0].strip() if len(r) > 0 else ''
        color        = r[1].strip() if len(r) > 1 else ''
        product_name = r[2].strip() if len(r) > 2 else ''
        bag_type     = r[3].strip() if len(r) > 3 else ''

        # Skip completely empty rows
        if not category and not color and not bag_type and not product_name:
            continue

        # Skip total rows (e.g. "TOTAL SUM", "SUM TOTAL", "LOCATION_TOTAL")
        row_text = (category + color + product_name + bag_type).lower()
        if 'total' in row_text or 'sum' in row_text:
            continue

        for (month, location), ci in headers['col_index'].items():
            raw_val = r[ci] if ci < len(r) else ''
            try:
                val_str = str(raw_val).replace(',', '').replace(' ', '').strip()
                if val_str.endswith('%'):
                    # Handle percentage values (e.g. "2900.00%")
                    qty = int(float(val_str.rstrip('%')) / 100)
                else:
                    qty = int(float(val_str))
            except ValueError:
                qty = 0

            region = get_region_for_location(location)

            rows.append({
                'Category': category,
                'Color':    color,
                'ProductName': product_name,
                'BagType':  bag_type,
                'Month':    month,
                'Location': location,
                'Region':   region,
                'Qty':      qty,
            })

    df = pd.DataFrame(rows)
    print(f"Long-format DataFrame: {len(df):,} rows x {len(df.columns)} cols")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# ❺  REPORT GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

# ── 5a. Monthly performance per location ─────────────────────────────────────
def report_monthly_by_location(df: pd.DataFrame) -> pd.DataFrame:
    """Bags sold per Location per Month (pivot table)."""
    pivot = (
        df.groupby(['Location', 'Month'])['Qty']
        .sum()
        .unstack(fill_value=0)
    )
    # Add row total
    pivot['TOTAL'] = pivot.sum(axis=1)
    # Add month column totals as a footer row
    totals_row = pivot.sum().rename('ALL LOCATIONS')
    pivot = pd.concat([pivot, totals_row.to_frame().T])

    # Attach region for context
    pivot.insert(0, 'Region',
        pivot.index.map(lambda loc: SHOP_REGION_MAP.get(loc, 'Unknown'))
    )
    return pivot


# ── 5b. Monthly performance per region ───────────────────────────────────────
def report_monthly_by_region(df: pd.DataFrame) -> pd.DataFrame:
    """Bags sold per Region per Month (pivot table)."""
    pivot = (
        df.groupby(['Region', 'Month'])['Qty']
        .sum()
        .unstack(fill_value=0)
    )
    pivot['TOTAL'] = pivot.sum(axis=1)
    totals_row     = pivot.sum().rename('ALL REGIONS')
    return pd.concat([pivot, totals_row.to_frame().T])


# ── 5c. Colour performance ────────────────────────────────────────────────────
def report_color_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Total bags per Colour, broken down by Month."""
    pivot = (
        df.groupby(['Color', 'Month'])['Qty']
        .sum()
        .unstack(fill_value=0)
    )
    pivot['TOTAL'] = pivot.sum(axis=1)
    pivot.sort_values('TOTAL', ascending=False, inplace=True)
    return pivot


# ── 5d. Category performance ──────────────────────────────────────────────────
def report_category_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Total bags per Category, broken down by Month."""
    pivot = (
        df.groupby(['Category', 'Month'])['Qty']
        .sum()
        .unstack(fill_value=0)
    )
    pivot['TOTAL'] = pivot.sum(axis=1)
    pivot.sort_values('TOTAL', ascending=False, inplace=True)
    return pivot


# ── 5e. Bag-type performance ──────────────────────────────────────────────────
def report_bagtype_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Total bags per BagType, broken down by Month."""
    pivot = (
        df.groupby(['BagType', 'Month'])['Qty']
        .sum()
        .unstack(fill_value=0)
    )
    pivot['TOTAL'] = pivot.sum(axis=1)
    pivot.sort_values('TOTAL', ascending=False, inplace=True)
    return pivot


# ── 5f. Color performance by region ──────────────────────────────────────────
def report_color_by_region(df: pd.DataFrame) -> pd.DataFrame:
    """Which colours sell most in each region."""
    tbl = (
        df.groupby(['Region', 'Color'])['Qty']
        .sum()
        .reset_index()
        .sort_values(['Region', 'Qty'], ascending=[True, False])
    )
    return tbl


# ── 5g. Per-location monthly colour breakdown ─────────────────────────────────
def report_location_color_monthly(df: pd.DataFrame, location: str) -> pd.DataFrame:
    """Detailed colour × month breakdown for a single location."""
    sub = df[df['Location'] == location]
    pivot = (
        sub.groupby(['Color', 'Month'])['Qty']
        .sum()
        .unstack(fill_value=0)
    )
    pivot['TOTAL'] = pivot.sum(axis=1)
    pivot.sort_values('TOTAL', ascending=False, inplace=True)
    return pivot


# ══════════════════════════════════════════════════════════════════════════════
# ❻  EXPORT — prints + saves to Excel with multiple sheets
# ══════════════════════════════════════════════════════════════════════════════
def export_reports(reports: dict, output_path: str = 'Annual_2026_Report.xlsx'):
    """Write all report DataFrames to a multi-sheet Excel file."""
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for sheet_name, df_report in reports.items():
            df_report.to_excel(writer, sheet_name=sheet_name[:31])   # Excel 31-char limit
    print(f"\nReport saved -> {output_path}")


def print_report(title: str, df_report: pd.DataFrame, max_rows: int = 30):
    sep = '─' * 70
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    print(df_report.head(max_rows).to_string())
    print(sep)


# ══════════════════════════════════════════════════════════════════════════════
# ❼  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def run_analytics():
    """End-to-end pipeline: fetch → parse → analyse → export."""
    ws  = get_worksheet()
    raw = fetch_raw(ws)

    if len(raw) < 3:
        print("Sheet has fewer than 3 rows - nothing to analyse.")
        return

    headers = parse_headers(raw)
    df      = build_dataframe(raw, headers)

    if df.empty:
        print("No data rows found after row 2.")
        return

    # ── Generate all reports ──────────────────────────────────────────────
    rpt_loc_monthly   = report_monthly_by_location(df)
    rpt_region_monthly = report_monthly_by_region(df)
    rpt_color         = report_color_performance(df)
    rpt_category      = report_category_performance(df)
    rpt_bagtype       = report_bagtype_performance(df)
    rpt_color_region  = report_color_by_region(df)

    # Per-location colour detail for every shop
    per_location_color_reports = {
        f"Clr_{loc[:24]}": report_location_color_monthly(df, loc)
        for loc in headers['locations']
    }

    # ── Print to console ──────────────────────────────────────────────────
    print_report("MONTHLY SALES BY LOCATION",  rpt_loc_monthly)
    print_report("MONTHLY SALES BY REGION",    rpt_region_monthly)
    print_report("COLOUR PERFORMANCE",         rpt_color)
    print_report("CATEGORY PERFORMANCE",       rpt_category)
    print_report("BAG-TYPE PERFORMANCE",       rpt_bagtype)
    print_report("COLOUR PERFORMANCE BY REGION", rpt_color_region)

    # ── Export to Excel ───────────────────────────────────────────────────
    all_reports = {
        'Monthly by Location': rpt_loc_monthly,
        'Monthly by Region':   rpt_region_monthly,
        'Colour Performance':  rpt_color,
        'Category Performance': rpt_category,
        'BagType Performance': rpt_bagtype,
        'Colour by Region':    rpt_color_region,
        **per_location_color_reports,
    }
    export_reports(all_reports)

    return df, headers, all_reports


if __name__ == '__main__':
    run_analytics()
