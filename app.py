"""
app.py — Annual Bags Sold 2026  |  Flask API  |  Port 5003
"""

from flask import Flask, jsonify, render_template, request
from sales import ( # type: ignore
    get_worksheet, fetch_raw, parse_headers,
    build_dataframe,
    report_monthly_by_location, report_monthly_by_region,
    report_color_performance, report_category_performance,
    report_bagtype_performance, report_color_by_region,
    report_location_color_monthly,
    SHOP_REGION_MAP, REGION_COLORS, get_region_for_location,
)
import pandas as pd
from datetime import datetime

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
        ws      = get_worksheet()
        raw     = fetch_raw(ws)
        headers = parse_headers(raw)
        df      = build_dataframe(raw, headers)
        active_months = get_active_months(df, headers)
        headers['months'] = active_months
        headers['active_months'] = active_months

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

@app.route('/api/summary')
def api_summary():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error', 'Sheet not loaded')}), 503
    
    df, active_months = get_filtered_df_and_months(raw_df, headers)
    monthly_totals = (
        (df.groupby('Month')['Qty'].sum())
        .reindex(active_months, fill_value=0)
        .to_dict()
    )

    total_bags = int(sum(monthly_totals.values()))

    # Use non-Total rows for other metrics
    data_df = df[df['Location'] != 'Total']
    
    def get_top_stat(col):
        if data_df.empty: return None, 0
        sums = data_df.groupby(col)['Qty'].sum()
        top_val = sums.idxmax()
        return top_val, int(sums.max())

    top_location, top_location_qty = get_top_stat('Location')
    top_color, top_color_qty = get_top_stat('Color')
    top_category, top_category_qty = get_top_stat('Category')
    top_region, top_region_qty = get_top_stat('Region')
    top_bagtype, top_bagtype_qty = get_top_stat('BagType')
    top_product, top_product_qty = get_top_stat('ProductName')

    # New Product KPIs
    focus_df = data_df[data_df['ProductName'].str.upper().str.startswith(tuple(FOCUS_PRODUCTS))]
    new_products_total = int(focus_df['Qty'].sum())
    
    prod_sums = focus_df.groupby('ProductName')['Qty'].sum()
    new_products_top = prod_sums.idxmax() if not focus_df.empty else '—'
    new_products_top_qty = int(prod_sums.max()) if not focus_df.empty else 0
    
    bag_sums = focus_df.groupby('BagType')['Qty'].sum()
    new_products_top_bag = bag_sums.idxmax() if not focus_df.empty else '—'
    new_products_top_bag_qty = int(bag_sums.max()) if not focus_df.empty else 0

    monthly_stats = []
    for m in active_months:
        m_df = data_df[data_df['Month'] == m]
        if not m_df.empty:
            loc_sums = m_df.groupby('Location')['Qty'].sum()
            total_sales = int(loc_sums.sum())
            if total_sales > 0:
                best_shop = loc_sums.idxmax()
                best_shop_qty = int(loc_sums.max())
                
                # Filter out empty strings before finding max to avoid empty labels
                m_df_valid_color = m_df[m_df['Color'] != '']
                best_color = m_df_valid_color.groupby('Color')['Qty'].sum().idxmax() if not m_df_valid_color.empty else '—'
                
                m_df_valid_cat = m_df[m_df['Category'] != '']
                best_cat = m_df_valid_cat.groupby('Category')['Qty'].sum().idxmax() if not m_df_valid_cat.empty else '—'
                
                m_df_valid_bag = m_df[m_df['BagType'] != '']
                best_bag = m_df_valid_bag.groupby('BagType')['Qty'].sum().idxmax() if not m_df_valid_bag.empty else '—'
                
                m_df_valid_prod = m_df[m_df['ProductName'] != '']
                best_prod = m_df_valid_prod.groupby('ProductName')['Qty'].sum().idxmax() if not m_df_valid_prod.empty else '—'
            else:
                best_shop, best_shop_qty = '—', 0
                best_color, best_cat, best_bag, best_prod = '—', '—', '—', '—'
        else:
            total_sales = 0
            best_shop, best_shop_qty = '—', 0
            best_color, best_cat, best_bag, best_prod = '—', '—', '—', '—'
            
        monthly_stats.append({
            'month': m,
            'total': total_sales,
            'best_shop': best_shop,
            'best_shop_qty': best_shop_qty,
            'best_color': best_color,
            'best_category': best_cat,
            'best_bagtype': best_bag,
            'best_product': best_prod
        })

    return jsonify({
        'total_bags': total_bags,
        'top_location': top_location,
        'top_location_qty': top_location_qty,
        'top_color':    top_color,
        'top_color_qty': top_color_qty,
        'top_category': top_category,
        'top_category_qty': top_category_qty,
        'top_region':   top_region,
        'top_region_qty': top_region_qty,
        'top_bagtype':  top_bagtype,
        'top_bagtype_qty': top_bagtype_qty,
        'top_product':  top_product,
        'top_product_qty': top_product_qty,
        'new_products_total': new_products_total,
        'new_products_top':   new_products_top,
        'new_products_top_qty': new_products_top_qty,
        'new_products_top_bag': new_products_top_bag,
        'new_products_top_bag_qty': new_products_top_bag_qty,
        'monthly_totals': monthly_totals,
        'monthly_stats': monthly_stats,
        'num_locations': len(headers['locations']),
        'num_months': len(headers['months']),
    })


@app.route('/api/monthly-by-location')
def api_monthly_by_location():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503
    
    df, months = get_filtered_df_and_months(raw_df, headers)

    result = []
    for loc in headers['locations']:
        sub  = df[df['Location'] == loc]
        row  = {'location': loc, 'region': get_region_for_location(loc)}
        total = 0
        for m in months:
            qty = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m]  = qty
            total  += qty
        row['total'] = total
        result.append(row)

    # sort by total desc
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/monthly-by-region')
def api_monthly_by_region():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503
    
    df, months = get_filtered_df_and_months(raw_df, headers)
    regions = df['Region'].unique().tolist()

    result = []
    for reg in regions:
        sub  = df[df['Region'] == reg]
        row  = {'region': reg, 'color': REGION_COLORS.get(reg, '#888')}
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
    colors = df.groupby('Color')['Qty'].sum().sort_values(ascending=False).index.tolist()

    result = []
    for c in colors:
        if not c:
            continue
        sub  = df[df['Color'] == c]
        row  = {'color': c}
        total = 0
        for m in months:
            qty = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m]  = qty
            total  += qty
        row['total'] = total
        result.append(row)

    # sort by total desc
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/category-performance')
def api_category_performance():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503
    
    df, months = get_filtered_df_and_months(raw_df, headers)
    cats   = df.groupby('Category')['Qty'].sum().sort_values(ascending=False).index.tolist()

    result = []
    for cat in cats:
        if not cat:
            continue
        sub   = df[df['Category'] == cat]
        row   = {'category': cat}
        total = 0
        for m in months:
            qty   = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m] = qty
            total += qty
        row['total'] = total
        result.append(row)

    # sort by total desc
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/bagtype-performance')
def api_bagtype_performance():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503
    
    df, months = get_filtered_df_and_months(raw_df, headers)
    bagtypes = df.groupby('BagType')['Qty'].sum().sort_values(ascending=False).index.tolist()

    result = []
    for bt in bagtypes:
        if not bt:
            continue
        sub   = df[df['BagType'] == bt]
        row   = {'bagtype': bt}
        total = 0
        for m in months:
            qty   = int(sub[sub['Month'] == m]['Qty'].sum())
            row[m] = qty
            total += qty
        row['total'] = total
        result.append(row)

    # sort by total desc
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/product-performance')
def api_product_performance():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error')}), 503
    
    df, months = get_filtered_df_and_months(raw_df, headers)
    products = df.groupby('ProductName')['Qty'].sum().sort_values(ascending=False).index.tolist()

    result = []
    for prod in products:
        if not prod:
            continue
        sub   = df[df['ProductName'] == prod]
        total = int(sub['Qty'].sum())
        if total <= 0:
            continue
            
        row   = {'product': prod, 'total': total}
        for m in months:
            row[m] = int(sub[sub['Month'] == m]['Qty'].sum())
        result.append(row)

    # sort by total desc
    result.sort(key=lambda x: x['total'], reverse=True)
    return jsonify({'months': months, 'data': result})


@app.route('/api/color-by-region')
def api_color_by_region():
    df, _ = get_df()
    if df is None:
        return jsonify({'error': _cache.get('error')}), 503
    tbl = (
        df.groupby(['Region', 'Color'])['Qty']
        .sum()
        .reset_index()
        .sort_values(['Region', 'Qty'], ascending=[True, False])
    )
    result = {}
    for _, row in tbl.iterrows():
        reg  = row['Region']
        if reg not in result:
            result[reg] = {'region': reg, 'color_hex': REGION_COLORS.get(reg, '#888'), 'colors': []}
        result[reg]['colors'].append({'color': row['Color'], 'qty': int(row['Qty'])})

    return jsonify(list(result.values()))


@app.route('/api/location/<location_name>')
def api_location_detail(location_name):
    df, headers = get_df()
    months = headers['months']
    sub    = df[df['Location'] == location_name]
    if sub.empty:
        return jsonify({'error': f'Location "{location_name}" not found'}), 404

    # Color breakdown
    colors = sub.groupby('Color')['Qty'].sum().sort_values(ascending=False).reset_index()
    color_data = colors.to_dict(orient='records')

    # Category breakdown
    cats = sub.groupby('Category')['Qty'].sum().sort_values(ascending=False).reset_index()
    cat_data = cats.to_dict(orient='records')

    # Monthly totals
    monthly = {m: int(sub[sub['Month'] == m]['Qty'].sum()) for m in months}

    return jsonify({
        'location': location_name,
        'region':   get_region_for_location(location_name),
        'total':    int(sub['Qty'].sum()),
        'monthly':  monthly,
        'colors':   color_data,
        'categories': cat_data,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Focus Products Analytics


# ─────────────────────────────────────────────────────────────────────────────
# Focus Products Analytics
# ─────────────────────────────────────────────────────────────────────────────
FOCUS_PRODUCTS = [
    'AMORA', 'ARM BAND', 'CATHY HANDBAG', 'CELINE SLING BAG', 'CESS', 'CHASE',
    'CLAIRE HB', 'COSMO', 'IMANI', 'LEGACY', 'LOOP BP', 'MANDY HB', 'MEGA',
    'MINI UMBRA', 'MONAH BP', 'MONTANA', 'NALA', 'PIONEER', 'PRIME',
    'SIERRA HANDBAG', 'SKYE HB', 'SPARK', 'SPLASH BACKPACK', 'TAJI', 'VOYAGE'
]

@app.route('/api/focus-analytics')
def api_focus_analytics():
    raw_df, headers = get_df()
    if raw_df is None:
        return jsonify({'error': _cache.get('error', 'Sheet not loaded')}), 503
        
    # Apply global month filter
    df, months = get_filtered_df_and_months(raw_df, headers)
    
    # Filter for focus products (using startswith to catch variations like "AMORA BLACK")
    focus_mask = df['ProductName'].str.upper().str.startswith(tuple(FOCUS_PRODUCTS))
    focus_df = df[focus_mask]
    
    def get_perf(groupby_col, key_name):
        if focus_df.empty: return []
        items = focus_df.groupby(groupby_col)['Qty'].sum().sort_values(ascending=False).index.tolist()
        res = []
        for item in items:
            row = {key_name: item}
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
        'months': months,
        'by_location': get_perf('Location', 'location'),
        'by_region':   get_perf('Region', 'region'),
        'by_color':    get_perf('Color', 'color'),
        'by_category': get_perf('Category', 'category'),
        'by_bagtype':  get_perf('BagType', 'bagtype'),
        'by_product':  get_perf('ProductName', 'product')

    })

if __name__ == '__main__':
    print("Annual Sales Dashboard  ->  http://localhost:5003")
    load_data()   # non-fatal: server starts even if sheet not yet shared
    if _cache.get('error'):
        print("[ACTION NEEDED] Share 'Annual_2026' with: retention@retention-485013.iam.gserviceaccount.com")
    app.run(debug=True, port=5003)
