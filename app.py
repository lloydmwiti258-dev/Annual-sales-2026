"""
app.py — Annual Bags Sold 2026  |  Flask API + Analytics  |  Port 5003

Sheet layout expected:
  Row 1, Col F+  : Month names  (e.g. Jan, Feb, … Dec)
  Row 2, Col F+  : Location/shop names  (dynamic; one column each; includes a "Total" column)
  Col A           : Bag category
  Col B           : Recognised colour
  Col C           : Product name
  Col D           : Bag type
  Data rows start : Row 3 onwards
"""

import os
import json
import gspread
import pandas as pd
from datetime import datetime
from flask import Flask, jsonify, render_template, request
from google.oauth2.service_account import Credentials


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

REGION_COLORS = {
    'Nairobi CBD':      '#3498db',
    'Coastal Region':   '#e74c3c',
    'Western & Nyanza': '#2ecc71',
    'Central Region':   '#f39c12',
    'Rift Valley':      '#9b59b6',
    'Diaspora':         '#1abc9c',
    'Reject Region':    '#7f8c8d',
    'Online':           '#3498db',
}

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
        if not os.path.exists(JSON_FILE_PATH):
            raise FileNotFoundError(
                f"Credentials not found. Set GOOGLE_CREDENTIALS env var or provide {JSON_FILE_PATH}"
            )
        creds = Credentials.from_service_account_file(JSON_FILE_PATH, scopes=SCOPES)
        print(f"OK  Authenticated via {JSON_FILE_PATH}")

    client = gspread.authorize(creds)
    sheet  = client.open_by_key(SHEET_ID)
    ws     = sheet.worksheet(WORKSHEET_NAME)
    print(f"OK  Connected  ->  '{SHEET_NAME}' / '{WORKSHEET_NAME}'")
    return ws


def fetch_raw(ws) -> list[list]:
    return ws.get_all_values()


# ══════════════════════════════════════════════════════════════════════════════
# ❸  HEADER PARSING
# ══════════════════════════════════════════════════════════════════════════════
def parse_headers(raw: list[list]) -> dict:
    month_row    = raw[0]
    location_row = raw[1]

    months_seen   = []
    col_index     = {}
    total_cols    = {}
    current_month = None

    for ci in range(5, len(month_row)):
        month_cell    = month_row[ci].strip()
        location_cell = location_row[ci].strip()

        if month_cell:
            current_month = month_cell
            if current_month not in months_seen:
                months_seen.append(current_month)

        if not current_month:
            continue

        if location_cell and 'total' in location_cell.lower():
            if current_month not in total_cols:
                total_cols[current_month] = ci
        elif location_cell:
            if (current_month, location_cell) not in col_index:
                col_index[(current_month, location_cell)] = ci

    locations = list(dict.fromkeys(loc for (_, loc) in col_index.keys()))

    print(f"Months    : {months_seen}")
    print(f"Locations : {locations}")

    return {
        'months':     months_seen,
        'locations':  locations,
        'col_index':  col_index,
        'total_cols': total_cols,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ❹  BUILD LONG-FORMAT DATAFRAME
# ══════════════════════════════════════════════════════════════════════════════
def build_dataframe(raw: list[list], headers: dict) -> pd.DataFrame:
    rows = []
    for r in raw[2:]:
        while len(r) < max(headers['col_index'].values(), default=0) + 1:
            r.append('')

        category     = r[0].strip() if len(r) > 0 else ''
        color        = r[1].strip() if len(r) > 1 else ''
        product_name = r[2].strip() if len(r) > 2 else ''
        bag_type     = r[3].strip() if len(r) > 3 else ''

        if not category and not color and not bag_type and not product_name:
            continue

        row_text = (category + color + product_name + bag_type).lower()
        if 'total' in row_text or 'sum' in row_text:
            continue

        for (month, location), ci in headers['col_index'].items():
            raw_val = r[ci] if ci < len(r) else ''
            try:
                val_str = str(raw_val).replace(',', '').replace(' ', '').strip()
                if val_str.endswith('%'):
                    qty = int(float(val_str.rstrip('%')) / 100)
                else:
                    qty = int(float(val_str))
            except ValueError:
                qty = 0

            rows.append({
                'Category':    category,
                'Color':       color,
                'ProductName': product_name,
                'BagType':     bag_type,
                'Month':       month,
                'Location':    location,
                'Region':      get_region_for_location(location),
                'Qty':         qty,
            })

    df = pd.DataFrame(rows)
    print(f"Long-format DataFrame: {len(df):,} rows x {len(df.columns)} cols")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# ❺  REPORT GENERATORS  (for standalone / Excel export use)
# ══════════════════════════════════════════════════════════════════════════════
def report_monthly_by_location(df: pd.DataFrame) -> pd.DataFrame:
    pivot = df.groupby(['Location', 'Month'])['Qty'].sum().unstack(fill_value=0)
    pivot['TOTAL'] = pivot.sum(axis=1)
    pivot = pd.concat([pivot, pivot.sum().rename('ALL LOCATIONS').to_frame().T])
    pivot.insert(0, 'Region', pivot.index.map(lambda loc: SHOP_REGION_MAP.get(loc, 'Unknown')))
    return pivot


def report_monthly_by_region(df: pd.DataFrame) -> pd.DataFrame:
    pivot = df.groupby(['Region', 'Month'])['Qty'].sum().unstack(fill_value=0)
    pivot['TOTAL'] = pivot.sum(axis=1)
    return pd.concat([pivot, pivot.sum().rename('ALL REGIONS').to_frame().T])


def report_color_performance(df: pd.DataFrame) -> pd.DataFrame:
    pivot = df.groupby(['Color', 'Month'])['Qty'].sum().unstack(fill_value=0)
    pivot['TOTAL'] = pivot.sum(axis=1)
    return pivot.sort_values('TOTAL', ascending=False)


def report_category_performance(df: pd.DataFrame) -> pd.DataFrame:
    pivot = df.groupby(['Category', 'Month'])['Qty'].sum().unstack(fill_value=0)
    pivot['TOTAL'] = pivot.sum(axis=1)
    return pivot.sort_values('TOTAL', ascending=False)


def report_bagtype_performance(df: pd.DataFrame) -> pd.DataFrame:
    pivot = df.groupby(['BagType', 'Month'])['Qty'].sum().unstack(fill_value=0)
    pivot['TOTAL'] = pivot.sum(axis=1)
    return pivot.sort_values('TOTAL', ascending=False)


def report_color_by_region(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(['Region', 'Color'])['Qty']
        .sum().reset_index()
        .sort_values(['Region', 'Qty'], ascending=[True, False])
    )


def report_location_color_monthly(df: pd.DataFrame, location: str) -> pd.DataFrame:
    sub   = df[df['Location'] == location]
    pivot = sub.groupby(['Color', 'Month'])['Qty'].sum().unstack(fill_value=0)
    pivot['TOTAL'] = pivot.sum(axis=1)
    return pivot.sort_values('TOTAL', ascending=False)


def export_reports(reports: dict, output_path: str = 'Annual_2026_Report.xlsx'):
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for sheet_name, df_report in reports.items():
            df_report.to_excel(writer, sheet_name=sheet_name[:31])
    print(f"\nReport saved -> {output_path}")


def run_analytics():
    """Standalone pipeline: fetch → parse → analyse → export to Excel."""
    ws  = get_worksheet()
    raw = fetch_raw(ws)
    if len(raw) < 3:
        print("Sheet has fewer than 3 rows — nothing to analyse.")
        return
    headers = parse_headers(raw)
    df      = build_dataframe(raw, headers)
    if df.empty:
        print("No data rows found after row 2.")
        return

    per_loc = {f"Clr_{loc[:24]}": report_location_color_monthly(df, loc) for loc in headers['locations']}
    all_reports = {
        'Monthly by Location':  report_monthly_by_location(df),
        'Monthly by Region':    report_monthly_by_region(df),
        'Colour Performance':   report_color_performance(df),
        'Category Performance': report_category_performance(df),
        'BagType Performance':  report_bagtype_performance(df),
        'Colour by Region':     report_color_by_region(df),
        **per_loc,
    }
    export_reports(all_reports)
    return df, headers, all_reports


# ══════════════════════════════════════════════════════════════════════════════
# ❻  FLASK APP
# ══════════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.auto_reload = True

@app.after_request
def add_cache_control(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ── In-memory cache (refreshed on /api/refresh) ───────────────────────────
_cache = {}

def load_data():
    try:
        ws      = get_worksheet()
        raw     = fetch_raw(ws)
        headers = parse_headers(raw)
        df      = build_dataframe(raw, headers)
        active  = get_active_months(df, headers)
        headers['months'] = active
        headers['active_months'] = active

        _cache['df']        = df
        _cache['headers']   = headers
        _cache['refreshed'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _cache['error']     = None
        print("Cache refreshed at", _cache['refreshed'])
    except Exception as e:
        _cache['error'] = str(e)
        print("[WARNING] Could not load sheet:", e)


def get_df():
    if 'df' not in _cache:
        load_data()
    if _cache.get('error'):
        return None, None
    return _cache['df'], _cache['headers']


def get_active_months(df: pd.DataFrame, headers: dict) -> list:
    month_totals = df.groupby('Month')['Qty'].sum()
    active = [m for m in headers['months'] if int(month_totals.get(m, 0)) != 0]
    return active or headers['months']


def get_filtered_df_and_months(df, headers):
    selected_month  = request.args.get('month')
    selected_region = request.args.get('region')
    selected_shop   = request.args.get('shop')

    filtered_df = df.copy()

    if selected_month and selected_month.lower() != 'overall':
        filtered_df = filtered_df[filtered_df['Month'].str.upper() == selected_month.upper()]
        months = [selected_month.upper()]
    else:
        months = get_active_months(df, headers)

    if selected_region and selected_region.lower() != 'all':
        filtered_df = filtered_df[filtered_df['Region'] == selected_region]

    if selected_shop and selected_shop.lower() != 'all':
        filtered_df = filtered_df[filtered_df['Location'] == selected_shop]

    return filtered_df, months


# ══════════════════════════════════════════════════════════════════════════════
# ❼  ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/refresh')
def api_refresh():
    load_data()
    if _cache.get('error'):
        return jsonify({'status': 'error', 'message': _cache['error']}), 503
    return jsonify({'status': 'ok', 'refreshed': _cache.get('refreshed')})


@app.route('/api/test-connection')
def api_test_connection():
    """Diagnostic endpoint — returns exactly what is failing."""
    info = {
        'sheet_id':        SHEET_ID,
        'worksheet_name':  WORKSHEET_NAME,
        'creds_env_set':   bool(os.environ.get('GOOGLE_CREDENTIALS')),
        'creds_file_exists': os.path.exists(JSON_FILE_PATH),
    }

    try:
        creds_raw = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_raw:
            creds = Credentials.from_service_account_info(json.loads(creds_raw), scopes=SCOPES)
            info['auth_source'] = 'GOOGLE_CREDENTIALS env var'
        else:
            creds = Credentials.from_service_account_file(JSON_FILE_PATH, scopes=SCOPES)
            info['auth_source'] = f'file: {JSON_FILE_PATH}'
        info['auth_ok'] = True
    except Exception as e:
        info['auth_ok'] = False
        info['auth_error'] = str(e)
        return jsonify(info), 500

    try:
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(SHEET_ID)
        info['spreadsheet_ok']    = True
        info['spreadsheet_title'] = sheet.title
        info['worksheets']        = [ws.title for ws in sheet.worksheets()]
    except Exception as e:
        info['spreadsheet_ok'] = False
        info['spreadsheet_error'] = str(e)
        return jsonify(info), 500

    info['target_worksheet_found'] = WORKSHEET_NAME in info['worksheets']
    return jsonify(info), 200 if info['target_worksheet_found'] else 404


@app.route('/api/status')
def api_status():
    if _cache.get('error'):
        return jsonify({'ok': False, 'error': _cache['error']}), 503
    return jsonify({'ok': True, 'refreshed': _cache.get('refreshed')})


@app.route('/api/meta')
def api_meta():
    df, headers = get_df()
    if headers is None:
        return jsonify({'error': _cache.get('error', 'Sheet not loaded')}), 503
    return jsonify({
        'months':        headers['months'],
        'locations':     headers['locations'],
        'region_colors': REGION_COLORS,
        'shop_region':   {loc: get_region_for_location(loc) for loc in headers['locations']},
        'refreshed':     _cache.get('refreshed', '—'),
    })


@app.route('/api/summary')
def api_summary():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error', 'Sheet not loaded')}), 503

    df, active_months = get_filtered_df_and_months(raw_df, headers)
    monthly_totals = (
        df.groupby('Month')['Qty'].sum()
        .reindex(active_months, fill_value=0)
        .to_dict()
    )
    total_bags = int(sum(monthly_totals.values()))
    data_df    = df[df['Location'] != 'Total']

    def get_top_stat(col):
        if data_df.empty: return None, 0
        sums = data_df.groupby(col)['Qty'].sum()
        return sums.idxmax(), int(sums.max())

    top_location,  top_location_qty  = get_top_stat('Location')
    top_color,     top_color_qty     = get_top_stat('Color')
    top_category,  top_category_qty  = get_top_stat('Category')
    top_region,    top_region_qty    = get_top_stat('Region')
    top_bagtype,   top_bagtype_qty   = get_top_stat('BagType')
    top_product,   top_product_qty   = get_top_stat('ProductName')

    focus_df = data_df[data_df['ProductName'].str.upper().str.startswith(tuple(FOCUS_PRODUCTS))]
    new_products_total = int(focus_df['Qty'].sum())
    prod_sums = focus_df.groupby('ProductName')['Qty'].sum()
    bag_sums  = focus_df.groupby('BagType')['Qty'].sum()
    new_products_top         = prod_sums.idxmax() if not focus_df.empty else '—'
    new_products_top_qty     = int(prod_sums.max()) if not focus_df.empty else 0
    new_products_top_bag     = bag_sums.idxmax()  if not focus_df.empty else '—'
    new_products_top_bag_qty = int(bag_sums.max()) if not focus_df.empty else 0

    monthly_stats = []
    for m in active_months:
        m_df = data_df[data_df['Month'] == m]
        if not m_df.empty:
            loc_sums    = m_df.groupby('Location')['Qty'].sum()
            total_sales = int(loc_sums.sum())
            if total_sales > 0:
                best_shop     = loc_sums.idxmax()
                best_shop_qty = int(loc_sums.max())
                def _best(col):
                    sub = m_df[m_df[col] != '']
                    return sub.groupby(col)['Qty'].sum().idxmax() if not sub.empty else '—'
                best_color = _best('Color')
                best_cat   = _best('Category')
                best_bag   = _best('BagType')
                best_prod  = _best('ProductName')
            else:
                best_shop, best_shop_qty = '—', 0
                best_color = best_cat = best_bag = best_prod = '—'
        else:
            total_sales = 0
            best_shop, best_shop_qty = '—', 0
            best_color = best_cat = best_bag = best_prod = '—'

        monthly_stats.append({
            'month': m, 'total': total_sales,
            'best_shop': best_shop, 'best_shop_qty': best_shop_qty,
            'best_color': best_color, 'best_category': best_cat,
            'best_bagtype': best_bag, 'best_product': best_prod,
        })

    return jsonify({
        'total_bags':              total_bags,
        'top_location':            top_location,
        'top_location_qty':        top_location_qty,
        'top_color':               top_color,
        'top_color_qty':           top_color_qty,
        'top_category':            top_category,
        'top_category_qty':        top_category_qty,
        'top_region':              top_region,
        'top_region_qty':          top_region_qty,
        'top_bagtype':             top_bagtype,
        'top_bagtype_qty':         top_bagtype_qty,
        'top_product':             top_product,
        'top_product_qty':         top_product_qty,
        'new_products_total':      new_products_total,
        'new_products_top':        new_products_top,
        'new_products_top_qty':    new_products_top_qty,
        'new_products_top_bag':    new_products_top_bag,
        'new_products_top_bag_qty': new_products_top_bag_qty,
        'monthly_totals':          monthly_totals,
        'monthly_stats':           monthly_stats,
        'num_locations':           len(headers['locations']),
        'num_months':              len(headers['months']),
    })


@app.route('/api/monthly-by-location')
def api_monthly_by_location():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503

    df, months = get_filtered_df_and_months(raw_df, headers)
    result = []
    for loc in headers['locations']:
        sub   = df[df['Location'] == loc]
        row   = {'location': loc, 'region': get_region_for_location(loc)}
        total = 0
        for m in months:
            qty = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m]  = qty
            total  += qty
        row['total'] = total
        result.append(row)
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/monthly-by-region')
def api_monthly_by_region():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503

    df, months = get_filtered_df_and_months(raw_df, headers)
    result = []
    for reg in df['Region'].unique():
        sub   = df[df['Region'] == reg]
        row   = {'region': reg, 'color': REGION_COLORS.get(reg, '#888')}
        total = 0
        for m in months:
            qty = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m]  = qty
            total  += qty
        row['total'] = total
        result.append(row)
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/color-performance')
def api_color_performance():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503

    df, months = get_filtered_df_and_months(raw_df, headers)
    result = []
    for c in df.groupby('Color')['Qty'].sum().sort_values(ascending=False).index:
        if not c: continue
        sub   = df[df['Color'] == c]
        row   = {'color': c}
        total = 0
        for m in months:
            qty = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m]  = qty
            total  += qty
        row['total'] = total
        result.append(row)
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/category-performance')
def api_category_performance():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503

    df, months = get_filtered_df_and_months(raw_df, headers)
    result = []
    for cat in df.groupby('Category')['Qty'].sum().sort_values(ascending=False).index:
        if not cat: continue
        sub   = df[df['Category'] == cat]
        row   = {'category': cat}
        total = 0
        for m in months:
            qty   = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m] = qty
            total += qty
        row['total'] = total
        result.append(row)
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/bagtype-performance')
def api_bagtype_performance():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503

    df, months = get_filtered_df_and_months(raw_df, headers)
    result = []
    for bt in df.groupby('BagType')['Qty'].sum().sort_values(ascending=False).index:
        if not bt: continue
        sub   = df[df['BagType'] == bt]
        row   = {'bagtype': bt}
        total = 0
        for m in months:
            qty   = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m] = qty
            total += qty
        row['total'] = total
        result.append(row)
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/product-performance')
def api_product_performance():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503

    df, months = get_filtered_df_and_months(raw_df, headers)
    result = []
    for prod in df.groupby('ProductName')['Qty'].sum().sort_values(ascending=False).index:
        if not prod: continue
        sub   = df[df['ProductName'] == prod]
        total = int(sub['Qty'].sum())
        if total <= 0: continue
        row = {'product': prod, 'total': total}
        for m in months:
            row[m] = int(sub[sub['Month'] == m]['Qty'].sum())
        result.append(row)
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/color-by-region')
def api_color_by_region():
    df, _ = get_df()
    if df is None:
        return jsonify({'error': _cache.get('error')}), 503
    tbl = (
        df.groupby(['Region', 'Color'])['Qty']
        .sum().reset_index()
        .sort_values(['Region', 'Qty'], ascending=[True, False])
    )
    result = {}
    for _, row in tbl.iterrows():
        reg = row['Region']
        if reg not in result:
            result[reg] = {'region': reg, 'color_hex': REGION_COLORS.get(reg, '#888'), 'colors': []}
        result[reg]['colors'].append({'color': row['Color'], 'qty': int(row['Qty'])})
    return jsonify(list(result.values()))


@app.route('/api/location/<location_name>')
def api_location_detail(location_name):
    df, headers = get_df()
    if df is None:
        return jsonify({'error': _cache.get('error')}), 503
    sub = df[df['Location'] == location_name]
    if sub.empty:
        return jsonify({'error': f'Location "{location_name}" not found'}), 404

    months   = headers['months']
    colors   = sub.groupby('Color')['Qty'].sum().sort_values(ascending=False).reset_index()
    cats     = sub.groupby('Category')['Qty'].sum().sort_values(ascending=False).reset_index()
    monthly  = {m: int(sub[sub['Month'] == m]['Qty'].sum()) for m in months}

    return jsonify({
        'location':   location_name,
        'region':     get_region_for_location(location_name),
        'total':      int(sub['Qty'].sum()),
        'monthly':    monthly,
        'colors':     colors.to_dict(orient='records'),
        'categories': cats.to_dict(orient='records'),
    })


# ══════════════════════════════════════════════════════════════════════════════
# ❽  FOCUS PRODUCTS ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
FOCUS_PRODUCTS = [
    'AMORA', 'ARM BAND', 'CATHY HANDBAG', 'CELINE SLING BAG', 'CESS', 'CHASE',
    'CLAIRE HB', 'COSMO', 'IMANI', 'LEGACY', 'LOOP BP', 'MANDY HB', 'MEGA',
    'MINI UMBRA', 'MONAH BP', 'MONTANA', 'NALA', 'PIONEER', 'PRIME',
    'SIERRA HANDBAG', 'SKYE HB', 'SPARK', 'SPLASH BACKPACK', 'TAJI', 'VOYAGE',
]

@app.route('/api/focus-analytics')
def api_focus_analytics():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error', 'Sheet not loaded')}), 503

    df, months = get_filtered_df_and_months(raw_df, headers)
    focus_df   = df[df['ProductName'].str.upper().str.startswith(tuple(FOCUS_PRODUCTS))]

    def get_perf(groupby_col, key_name):
        if focus_df.empty: return []
        res = []
        for item in focus_df.groupby(groupby_col)['Qty'].sum().sort_values(ascending=False).index:
            row   = {key_name: item}
            if groupby_col == 'Location':
                row['region'] = get_region_for_location(item)
            total = 0
            for m in months:
                val = int(focus_df[(focus_df[groupby_col] == item) & (focus_df['Month'] == m)]['Qty'].sum())
                row[m] = val
                total += val
            row['total'] = total
            if total > 0:
                res.append(row)
        return res

    return jsonify({
        'months':      months,
        'by_location': get_perf('Location',    'location'),
        'by_region':   get_perf('Region',      'region'),
        'by_color':    get_perf('Color',       'color'),
        'by_category': get_perf('Category',    'category'),
        'by_bagtype':  get_perf('BagType',     'bagtype'),
        'by_product':  get_perf('ProductName', 'product'),
    })


# ══════════════════════════════════════════════════════════════════════════════
# ❾  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("Annual Sales Dashboard  ->  http://localhost:5003")
    load_data()
    if _cache.get('error'):
        print("[ACTION NEEDED] Share 'Annual_2026' with: retention@retention-485013.iam.gserviceaccount.com")
    app.run(debug=True, port=5003)
