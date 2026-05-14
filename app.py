"""
app.py — Annual Bags Sold 2026  |  Flask API  |  Port 5003
"""

from flask import Flask, jsonify, render_template, request
from SALES import ( # type: ignore
    get_worksheet, fetch_raw, parse_headers,
    build_dataframe,
    report_monthly_by_location, report_monthly_by_region,
    report_color_performance, report_category_performance,
    report_bagtype_performance, report_color_by_region,
    report_location_color_monthly,
    SHOP_REGION_MAP, REGION_COLORS, get_region_for_location,
    FOCUS_PRODUCTS,
)
import pandas as pd
from datetime import datetime

from integrated_data import process_data, get_correlations, get_insights

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

# ── cached data (refreshed on /api/refresh) ───────────────────────────────
_cache = {}

def load_data():
    try:
        data_dict = process_data()
        _cache['data_dict'] = data_dict
        _cache['refreshed'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _cache['error']     = None
        print("Integrated cache refreshed at", _cache['refreshed'])
    except Exception as e:
        _cache['error'] = str(e)
        print("[WARNING] Could not load integrated data:", e)

def get_data():
    if 'data_dict' not in _cache:
        load_data()
    if _cache.get('error'):
        return None
    return _cache['data_dict']


def get_df():
    if 'df' not in _cache:
        load_data()
    if _cache.get('error'):
        return None, None
    return _cache['df'], _cache['headers']


def get_active_months(df: pd.DataFrame, headers: dict) -> list:
    """Return only months that have actual sales data, preserving header order."""
    month_totals = df.groupby('Month')['Qty'].sum()
    active_months = [m for m in headers['months'] if int(month_totals.get(m, 0)) != 0]
    return active_months or headers['months']


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def pivot_to_json(pivot: pd.DataFrame):
    """Convert a pivot DataFrame to a JSON-serialisable dict."""
    pivot = pivot.copy()
    # Reset multi-index if needed
    if pivot.index.name or pivot.index.dtype == object:
        pivot = pivot.reset_index()
    return pivot.to_dict(orient='records')


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/refresh')
def api_refresh():
    load_data()
    if _cache.get('error'):
        return jsonify({'status': 'error', 'message': _cache['error']}), 503
    return jsonify({'status': 'ok', 'refreshed': _cache.get('refreshed')})


@app.route('/api/status')
def api_status():
    """Health check — returns connection error if sheet not yet shared."""
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


def get_filtered_df_and_months(df, headers):
    selected_month = request.args.get('month')
    selected_region = request.args.get('region')
    selected_shop = request.args.get('shop')
    
    filtered_df = df
    
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

def get_pivot_data(df, index_col, months, include_region=False):
    if df.empty:
        return []
    
    # Use pivot_table for fast aggregation
    pivot = df.pivot_table(
        index=index_col, 
        columns='Month', 
        values='Qty', 
        aggfunc='sum', 
        fill_value=0
    )
    
    # Ensure all requested months are present and in correct order
    for m in months:
        if m not in pivot.columns:
            pivot[m] = 0
    
    pivot = pivot[months]
    pivot['total'] = pivot.sum(axis=1)
    pivot = pivot.sort_values('total', ascending=False)
    
    # Reset index to make the index_col a regular column
    result_df = pivot.reset_index()
    
    # Rename columns to match frontend expectations (index_col becomes lowercase)
    result_df.columns.name = None
    rename_map = {index_col: index_col.lower()}
    if index_col == 'ProductName': rename_map = {'ProductName': 'product'}
    if index_col == 'BagType':     rename_map = {'BagType': 'bagtype'}
    result_df = result_df.rename(columns=rename_map)
    
    if include_region and index_col == 'Location':
        result_df['region'] = result_df['location'].map(get_region_for_location)
    
    return result_df.to_dict(orient='records')

@app.route('/api/integrated-dashboard')
def api_integrated_dashboard():
    data_dict = get_data()
    if not data_dict:
        return jsonify({'error': _cache.get('error', 'Data not loaded')}), 503
    
    master = data_dict['master']
    
    # Filtering
    cat = request.args.get('category')
    bt = request.args.get('bagtype')
    prod = request.args.get('product')
    color = request.args.get('color')
    
    df = master.copy()
    if cat and cat != 'All': df = df[df['Category'] == cat]
    if bt and bt != 'All': df = df[df['Bag Type'] == bt]
    if prod and prod != 'All': df = df[df['Product Name'] == prod]
    if color and color != 'All': df = df[df['Color'] == color]
    
    # KPI Calculations
    summary = {
        'total_sales': int(df['Total Sales'].sum()),
        'total_stock': int(df['Total Stock'].sum()),
        'total_dispatch': int(df['Total Dispatch'].sum()),
        'total_production': int(df['Bags stitched'].sum()),
        'warehouse_availability': int(df['Effective Warehouse Stock'].sum()),
        'marketing_totals': int(df['Total Marketing'].sum()),
    }
    
    # Add target metrics
    target_df = data_dict['target_df']
    summary['target_sales'] = int(target_df['Monthly sales target'].sum())
    summary['actual_sales_target'] = int(target_df['Actual sales'].sum())
    summary['total_deficit'] = int(target_df['Deficit'].sum())
    summary['target_achievement'] = round((summary['actual_sales_target'] / summary['target_sales'] * 100), 2) if summary['target_sales'] > 0 else 0
    
    # Correlation Data
    correlations = get_correlations(data_dict)
    
    return jsonify({
        'summary': summary,
        'master_data': df.to_dict(orient='records'),
        'correlations': correlations.to_dict(orient='records'),
        'refreshed': _cache.get('refreshed'),
        'filters': {
            'categories': sorted(master['Category'].unique().tolist()),
            'bagtypes': sorted(master['Bag Type'].unique().tolist()),
            'products': sorted(master['Product Name'].unique().tolist()),
            'colors': sorted(master['Color'].unique().tolist()),
        }
    })

@app.route('/api/insights')
def api_get_insights():
    data_dict = get_data()
    if not data_dict:
        return jsonify({'error': 'Data not loaded'}), 503
    return jsonify(get_insights(data_dict))

@app.route('/api/refresh')
def api_refresh():
    load_data()
    if _cache.get('error'):
        return jsonify({'status': 'error', 'message': _cache['error']}), 503
    return jsonify({'status': 'ok', 'refreshed': _cache.get('refreshed')})

if __name__ == '__main__':
    print("Integrated Operations Dashboard -> http://localhost:5005")
    load_data()
    app.run(debug=True, port=5005)
