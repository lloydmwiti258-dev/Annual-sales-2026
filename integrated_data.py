import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import numpy as np
import os
import json

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
JSON_FILE_PATH = r'C:\Users\Administrator\Downloads\retention-485013-974e48474123.json'
SHEET_NAME     = 'SALES & INVENTORY DASHBOARD'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

def get_client():
    env_creds = os.environ.get('GOOGLE_CREDENTIALS')
    if env_creds:
        try:
            creds_info = json.loads(env_creds)
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        except Exception as e:
            print(f"Error parsing GOOGLE_CREDENTIALS: {e}")
            creds = Credentials.from_service_account_file(JSON_FILE_PATH, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(JSON_FILE_PATH, scopes=SCOPES)
    return gspread.authorize(creds)

def fetch_sheet_as_df(client, sheet_name, worksheet_name):
    try:
        sh = client.open(sheet_name)
        ws = sh.worksheet(worksheet_name)
        data = ws.get_all_values()
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data[1:], columns=data[0])
    except Exception as e:
        print(f"Error fetching {worksheet_name}: {e}")
        return pd.DataFrame()

def clean_numeric(val):
    if isinstance(val, str):
        val = val.replace(',', '').replace(' ', '').replace('$', '').strip()
        if not val or val == '-': return 0
        try:
            return float(val)
        except ValueError:
            return 0
    return val if isinstance(val, (int, float)) else 0

def process_data():
    client = get_client()
    
    # 1. Fetch all sheets
    sheets = ['SALE', 'MARKETING', 'STOCKS', 'PRODUCTION', 'WAREHOUSE', 'DISPATCH', 'MONTHLY TARGET']
    dfs = {}
    for s in sheets:
        dfs[s] = fetch_sheet_as_df(client, SHEET_NAME, s)
        # Basic cleanup: strip column names
        dfs[s].columns = [c.strip() for c in dfs[s].columns]

    # 2. Process Sales
    # Structure: Category, Color, Product Name, Bag Type, [Shops...], Total Sales
    sales_df = dfs['SALE']
    shop_cols = [c for c in sales_df.columns if c not in ['Category', 'Color', 'Product Name', 'Bag Type', 'Total Sales']]
    for col in shop_cols + ['Total Sales']:
        sales_df[col] = sales_df[col].apply(clean_numeric)
    
    # 3. Process Marketing
    # Structure: Category, Color, Product Name, Bag Type, Kenya, Sinza, Uganda
    mkt_df = dfs['MARKETING']
    mkt_cols = ['Kenya', 'Sinza', 'Uganda']
    for col in mkt_cols:
        if col in mkt_df.columns:
            mkt_df[col] = mkt_df[col].apply(clean_numeric)
    mkt_df['Total Marketing'] = mkt_df[mkt_cols].sum(axis=1)

    # 4. Process Stocks
    # Structure same as Sales. Combine KTDA MAIN STORE with Warehouse.
    stocks_df = dfs['STOCKS']
    stock_shop_cols = [c for c in stocks_df.columns if c not in ['Category', 'Color', 'Product Name', 'Bag Type', 'Total Stock', 'KTDA MAIN STORE']]
    for col in stocks_df.columns:
        if col not in ['Category', 'Color', 'Product Name', 'Bag Type']:
            stocks_df[col] = stocks_df[col].apply(clean_numeric)
    
    # 5. Process Production
    # Structure: Bags in cut store, Bags issued for stitching, Stitching WIP
    prod_df = dfs['PRODUCTION']
    prod_cols = ['Bags in cut store', 'Bags issued for stitching', 'Stitching WIP']
    for col in prod_df.columns:
        if col not in ['Category', 'Color', 'Product Name', 'Bag Type']:
            prod_df[col] = prod_df[col].apply(clean_numeric)

    # 6. Process Warehouse
    # Structure: Finished stock, WIP to finishing, Bags stitched, Bags finished
    wh_df = dfs['WAREHOUSE']
    for col in wh_df.columns:
        if col not in ['Category', 'Color', 'Product Name', 'Bag Type']:
            wh_df[col] = wh_df[col].apply(clean_numeric)

    # 7. Process Dispatch
    # Structure: Dispatch to shops
    dispatch_df = dfs['DISPATCH']
    for col in dispatch_df.columns:
        if col not in ['Category', 'Color', 'Product Name', 'Bag Type']:
            dispatch_df[col] = dispatch_df[col].apply(clean_numeric)

    # 8. Process Monthly Target
    # Structure: Bag type, Category, Monthly sales target, Actual sales, Deficit
    target_df = dfs['MONTHLY TARGET']
    for col in target_df.columns:
        if col not in ['Bag type', 'Category']:
            target_df[col] = target_df[col].apply(clean_numeric)

    # --- MERGING & CORRELATION BASICS ---
    # We'll use Category, Color, Product Name, Bag Type as the key for most
    merge_keys = ['Category', 'Color', 'Product Name', 'Bag Type']
    
    # Integrated Master DF
    master = sales_df[merge_keys + ['Total Sales']].copy()
    
    # Join Marketing
    master = master.merge(mkt_df[merge_keys + ['Total Marketing']], on=merge_keys, how='outer')
    
    # Join Stocks
    stocks_summary = stocks_df[merge_keys + ['Total Stock', 'KTDA MAIN STORE']].copy()
    master = master.merge(stocks_summary, on=merge_keys, how='outer')
    
    # Join Production
    prod_summary = prod_df[merge_keys + ['Bags in cut store', 'Bags issued for stitching', 'Stitching WIP']].copy()
    master = master.merge(prod_summary, on=merge_keys, how='outer')
    
    # Join Warehouse
    wh_summary = wh_df[merge_keys + ['Finished stock', 'WIP to finishing', 'Bags stitched', 'Bags finished']].copy()
    master = master.merge(wh_summary, on=merge_keys, how='outer')
    
    # Join Dispatch
    disp_summary = dispatch_df[merge_keys + ['Total Dispatch']].copy() if 'Total Dispatch' in dispatch_df.columns else dispatch_df[merge_keys].copy()
    # If 'Total Dispatch' doesn't exist, sum shop columns
    if 'Total Dispatch' not in dispatch_df.columns:
        disp_shop_cols = [c for c in dispatch_df.columns if c not in merge_keys]
        dispatch_df['Total Dispatch'] = dispatch_df[disp_shop_cols].sum(axis=1)
    master = master.merge(dispatch_df[merge_keys + ['Total Dispatch']], on=merge_keys, how='outer')

    # Join Target (Note: Target is often by Category/Bag Type only)
    # We'll handle target differently in the correlation section
    
    master.fillna(0, inplace=True)

    # Combined Warehouse stock = Warehouse Finished Stock + KTDA MAIN STORE
    master['Effective Warehouse Stock'] = master['Finished stock'] + master['KTDA MAIN STORE']
    
    return {
        'master': master,
        'sales_df': sales_df,
        'mkt_df': mkt_df,
        'stocks_df': stocks_df,
        'prod_df': prod_df,
        'wh_df': wh_df,
        'dispatch_df': dispatch_df,
        'target_df': target_df
    }

def get_correlations(data_dict):
    master = data_dict['master']
    target_df = data_dict['target_df']
    
    # One: Sales, Stocks, Warehouse (add KTDA Main Store and WIP), Cut in store and Deficit
    # Deficit comes from the Target sheet, we need to map it back if possible or use a simplified mapping
    # Let's aggregate master by Category/Bag Type to match Target sheet
    
    # Two: Sales, Dispatch, Stitching and Deficit
    
    # Three: Sales, Marketing, Stocks, and Deficit
    
    # Four: Target, Sales and Deficit
    
    # Mapping Deficit to Master
    # Target sheet usually has Category and Bag Type.
    target_agg = target_df.groupby(['Category', 'Bag type'])[['Monthly sales target', 'Actual sales', 'Deficit']].sum().reset_index()
    target_agg.rename(columns={'Bag type': 'Bag Type'}, inplace=True)
    
    master_agg = master.groupby(['Category', 'Bag Type']).agg({
        'Total Sales': 'sum',
        'Total Stock': 'sum',
        'Effective Warehouse Stock': 'sum',
        'WIP to finishing': 'sum',
        'Bags in cut store': 'sum',
        'Total Dispatch': 'sum',
        'Bags stitched': 'sum',
        'Stitching WIP': 'sum',
        'Total Marketing': 'sum'
    }).reset_index()
    
    corr_df = master_agg.merge(target_agg, on=['Category', 'Bag Type'], how='left').fillna(0)
    
    return corr_df

def get_insights(data_dict):
    master = data_dict['master']
    corr_df = get_correlations(data_dict)
    
    insights = []
    
    # 1. Low Stock Alerts
    low_stock = master[master['Total Stock'] < master['Total Sales'] * 0.2] # Arbitrary threshold
    if not low_stock.empty:
        insights.append({
            'type': 'warning',
            'title': 'Low Stock Alert',
            'message': f"{len(low_stock)} products have stock levels below 20% of their sales volume."
        })
        
    # 2. Overstock Analysis
    overstock = master[master['Total Stock'] > master['Total Sales'] * 3]
    if not overstock.empty:
        insights.append({
            'type': 'info',
            'title': 'Overstock Warning',
            'message': f"{len(overstock)} products have stock levels exceeding 3x their sales volume."
        })
        
    # 3. High Demand / Slow Moving
    high_demand = master.sort_values('Total Sales', ascending=False).head(5)
    slow_moving = master[master['Total Sales'] == 0].sort_values('Total Stock', ascending=False).head(5)
    
    # 4. Marketing/Sales Mismatch
    mismatch = master[(master['Total Marketing'] > 0) & (master['Total Sales'] == 0)]
    if not mismatch.empty:
        insights.append({
            'type': 'caution',
            'title': 'Marketing Mismatch',
            'message': f"{len(mismatch)} products are being marketed but have zero sales."
        })

    return insights
