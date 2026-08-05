import sys
import os
import json
import threading
import requests
import pandas as pd
import flet as ft

# נתיב בטוח לשמירת קבצים מקומיים - באנדרואיד זה יצביע לתיקיית הקבצים הפנימית והקבועה של האפליקציה
SAVE_DIR = os.path.expanduser("~")
SAVE_FILE = os.path.join(SAVE_DIR, "gedroeid_saved_data.json")

def load_local_state():
    """קורא את הנתונים השמורים מהקובץ המקומי"""
    try:
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        pass
    return {}

def save_local_state(state):
    """שומר את הנתונים לקובץ מקומי קבוע"""
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        pass

def safe_to_float(value):
    """ממיר ערך טקסטואלי למספר בצורה בטוחה (כולל אחוזים ופסיקים)."""
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text or text == "---":
        return None

    text = text.replace('%', '').replace(',', '')
    try:
        return float(text)
    except ValueError:
        return None

def process_data(df):
    """לוגיקת עיבוד הנתונים המקורית - נשארה ללא שינוי"""
    if df.empty:
        return df
        
    df.columns = [str(col).upper() for col in df.columns]
    original_df = df.copy()
    
    id_col = 'FUND_ID' if 'FUND_ID' in df.columns else 'ID'
    name_col = 'FUND_NAME' if 'FUND_NAME' in df.columns else 'NAME'

    # סינון קשיח למסלולי גמל להשקעה לפי שם המסלול
    if name_col in df.columns:
        name_text = df[name_col].astype(str)
        investment_mask = name_text.str.contains('להשקעה', na=False, regex=False)
        altshuler_saving_mask = (
            name_text.str.contains('אלטשולר', na=False, regex=False) &
            name_text.str.contains('חיסכון', na=False, regex=False)
        )
        df = df[investment_mask | altshuler_saving_mask]

    # גיבוי לפורמטים ישנים יותר לפי עמודות סוג מוצר
    type_candidates = ['SUG_KUPA_DESC', 'SUG_KUPA', 'PRODUCT_TYPE_DESC', 'PRODUCT_TYPE']
    type_col = next((col for col in type_candidates if col in df.columns), None)
    if type_col and not df.empty:
        type_text = df[type_col].astype(str)
        type_mask = (
            type_text.str.contains('גמל', na=False, regex=False) &
            type_text.str.contains('להשקעה', na=False, regex=False)
        )

        if name_col in df.columns:
            name_text = df[name_col].astype(str)
            altshuler_saving_mask = (
                name_text.str.contains('אלטשולר', na=False, regex=False) &
                name_text.str.contains('חיסכון', na=False, regex=False)
            )
            df = df[type_mask | altshuler_saving_mask]
        else:
            df = df[type_mask]

    # רשת ביטחון נוספת
    if df.empty and name_col in original_df.columns:
        fallback_name_col = name_col
        name_text = original_df[fallback_name_col].astype(str)
        investment_mask = name_text.str.contains('להשקעה', na=False, regex=False)
        altshuler_saving_mask = (
            name_text.str.contains('אלטשולר', na=False, regex=False) &
            name_text.str.contains('חיסכון', na=False, regex=False)
        )
        df = original_df[investment_mask | altshuler_saving_mask]

    if df.empty:
        return df

    if id_col in df.columns:
        trailing_12_by_id = {}
        if 'MONTHLY_YIELD' in df.columns:
            date_col = None
            if 'REPORT_PERIOD' in df.columns:
                df['REPORT_PERIOD_SORT'] = pd.to_numeric(df['REPORT_PERIOD'], errors='coerce')
                date_col = 'REPORT_PERIOD_SORT'
            elif 'TKUFA_DIVUACH' in df.columns:
                df['TKUFA_SORT'] = pd.to_datetime(df['TKUFA_DIVUACH'], errors='coerce', dayfirst=True)
                date_col = 'TKUFA_SORT'

            if date_col is not None:
                monthly_df = df[[id_col, 'MONTHLY_YIELD', date_col]].copy()
                monthly_df['MONTHLY_YIELD_NUM'] = pd.to_numeric(monthly_df['MONTHLY_YIELD'], errors='coerce')
                monthly_df = monthly_df.dropna(subset=[id_col, date_col, 'MONTHLY_YIELD_NUM'])

                for fund_id, grp in monthly_df.groupby(id_col):
                    recent = grp.sort_values(date_col).tail(12)
                    if len(recent) < 12:
                        continue
                    monthly_returns = recent['MONTHLY_YIELD_NUM'] / 100.0
                    trailing_12 = ((1.0 + monthly_returns).prod() - 1.0) * 100.0
                    trailing_12_by_id[fund_id] = trailing_12

        if 'REPORT_PERIOD' in df.columns:
            df['REPORT_PERIOD_SORT'] = pd.to_numeric(df['REPORT_PERIOD'], errors='coerce')
            df = df.sort_values('REPORT_PERIOD_SORT').drop_duplicates(subset=[id_col], keep='last')
        elif 'TKUFA_DIVUACH' in df.columns:
            df['TKUFA_SORT'] = pd.to_datetime(df['TKUFA_DIVUACH'], errors='coerce', dayfirst=True)
            df = df.sort_values('TKUFA_SORT').drop_duplicates(subset=[id_col], keep='last')
        
        df['Search_Key'] = df[id_col].astype(str) + " - " + df[name_col].astype(str)

        if trailing_12_by_id:
            df['תשואה 12 חודשים אחרונים'] = df[id_col].map(trailing_12_by_id)
        else:
            df['תשואה 12 חודשים אחרונים'] = None
    else:
        df['Search_Key'] = df[name_col].astype(str)
        df['תשואה 12 חודשים אחרונים'] = None

    metric_sources = {
        'תשואה חודש אחרון': ['TSUA_HODESH_AHARON', 'MONTHLY_YIELD'],
        'תשואה 12 חודשים אחרונים': ['תשואה 12 חודשים אחרונים'],
        'תשואה שנה אחרונה': ['TSUA_SHANA_AHARONA', 'YEAR_TO_DATE_YIELD'],
        'תשואה 3 שנים': ['TSUA_3_SHANIM', 'YIELD_TRAILING_3_YRS'],
        'תשואה 5 שנים': ['TSUA_5_SHANIM', 'YIELD_TRAILING_5_YRS'],
        'מדד שארפ': ['SHARPE_RATIO', 'SHARPE', 'SHARPE_INDEX']
    }

    output = pd.DataFrame()
    output['שם ומספר מסלול'] = df['Search_Key']
    for label, candidates in metric_sources.items():
        src = next((col for col in candidates if col in df.columns), None)
        output[label] = df[src] if src else None

    return_cols = ['תשואה חודש אחרון', 'תשואה 12 חודשים אחרונים', 'תשואה שנה אחרונה', 'תשואה 3 שנים', 'תשואה 5 שנים']
    avg_values = []
    for _, row in output.iterrows():
        numeric_vals = [safe_to_float(row.get(col)) for col in return_cols]
        numeric_vals = [val for val in numeric_vals if val is not None]
        avg_values.append(sum(numeric_vals) / len(numeric_vals) if numeric_vals else None)
    output['ממוצע תשואות'] = avg_values

    df_clean = output
    if 'שם ומספר מסלול' in df_clean.columns:
        df_clean = df_clean.drop_duplicates(subset=['שם ומספר מסלול'], keep='first')
    
    return df_clean

def main(page: ft.Page):
    page.title = "השוואת קופות גמל להשקעה"
    page.rtl = True # תמיכה מושלמת בעברית!
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    # ניהול מצב (State) - קריאת נתונים מקובץ מקומי במקום זיכרון זמני
    local_state = load_local_state()
    
    df_clean = pd.DataFrame()
    added_funds = local_state.get("added_funds", [])
    invested_funds = set(local_state.get("invested_funds", []))
    funds_list = []
    
    sort_column_idx = local_state.get("sort_column_idx", 3)
    sort_ascending = local_state.get("sort_ascending", False)

    # רכיבי UI
    status_text = ft.Text("⏳ מוריד נתונים עדכניים ממשרד האוצר... אנא המתן.", color=ft.Colors.ORANGE_700, weight=ft.FontWeight.BOLD)
    
    search_field = ft.TextField(
        label="הקלד שם מסלול או מספר קופה...",
        on_change=lambda e: update_search_suggestions(e.control.value),
        disabled=True,
        expand=True
    )
    
    search_results_column = ft.Column(visible=False)

    col_specs = [
        ('שם ומספר מסלול', False),
        ('תשואה חודש אחרון', True),
        ('תשואה 12 חודשים אחרונים', True),
        ('תשואה שנה אחרונה', True),
        ('תשואה 3 שנים', True),
        ('תשואה 5 שנים', True),
        ('ממוצע תשואות', True),
        ('מדד שארפ', False),
        ('מושקע', False) 
    ]

    def save_state():
        """אורז את הנתונים הנוכחיים וכותב אותם לקובץ"""
        state_dict = {
            "added_funds": added_funds,
            "invested_funds": list(invested_funds),
            "sort_column_idx": sort_column_idx,
            "sort_ascending": sort_ascending
        }
        save_local_state(state_dict)

    def on_sort(e: ft.DataColumnSortEvent):
        nonlocal sort_column_idx, sort_ascending
        sort_column_idx = e.column_index
        sort_ascending = e.ascending
        save_state() # שמירת בחירת המיון של המשתמש לקובץ
        refresh_table()

    # יצירת טבלה
    columns = []
    for i, (col_name, _) in enumerate(col_specs):
        columns.append(
            ft.DataColumn(
                ft.Text(col_name, weight=ft.FontWeight.BOLD),
                on_sort=on_sort if i < 8 else None
            )
        )

    data_table = ft.DataTable(
        columns=columns,
        show_checkbox_column=True, 
        sort_column_index=sort_column_idx,
        sort_ascending=sort_ascending,
        heading_row_color=ft.Colors.BLUE_GREY_50,
    )

    table_container = ft.Row([data_table], scroll=ft.ScrollMode.ALWAYS, expand=True)

    def toggle_invested(fund_name):
        if fund_name in invested_funds:
            invested_funds.remove(fund_name)
        else:
            invested_funds.add(fund_name)
        save_state()
        refresh_table()

    def refresh_table():
        if df_clean.empty:
            return
            
        data_table.sort_column_index = sort_column_idx
        data_table.sort_ascending = sort_ascending

        # מיון הנתונים
        sort_col_name = col_specs[sort_column_idx][0]
        
        def get_sort_val(fund_name):
            row = df_clean[df_clean['שם ומספר מסלול'] == fund_name]
            if row.empty: return -999.0
            val = safe_to_float(row.iloc[0].get(sort_col_name))
            return val if val is not None else -999.0

        sorted_funds = sorted(added_funds, key=get_sort_val, reverse=not sort_ascending)
        
        rows = []
        for fund_name in sorted_funds:
            fund_data = df_clean[df_clean['שם ומספר מסלול'] == fund_name]
            if fund_data.empty: continue
            fund_row = fund_data.iloc[0]
            
            cells = []
            for col_idx, (col_name, is_percent) in enumerate(col_specs):
                if col_name == 'מושקע':
                    is_inv = fund_name in invested_funds
                    icon = ft.Icons.STAR if is_inv else ft.Icons.STAR_BORDER
                    color = ft.Colors.AMBER if is_inv else ft.Colors.GREY
                    cells.append(ft.DataCell(ft.IconButton(icon=icon, icon_color=color, on_click=lambda e, fn=fund_name: toggle_invested(fn))))
                    continue
                    
                if col_name == 'שם ומספר מסלול':
                    cells.append(ft.DataCell(ft.Text(fund_name, width=200)))
                    continue

                val = fund_row.get(col_name, None)
                num_val = safe_to_float(val)
                
                if num_val is None:
                    display_text = "---"
                    text_color = ft.Colors.BLACK
                else:
                    display_text = f"{num_val:.2f}%" if is_percent else f"{num_val:.2f}"
                    if num_val > 0:
                        text_color = ft.Colors.GREEN_600
                    elif num_val < 0:
                        text_color = ft.Colors.RED_600
                    else:
                        text_color = ft.Colors.BLACK

                cells.append(ft.DataCell(ft.Text(display_text, color=text_color)))
            
            row_color = ft.Colors.GREEN_50 if fund_name in invested_funds else ft.Colors.TRANSPARENT
            rows.append(ft.DataRow(cells=cells, data=fund_name, color=row_color))

        data_table.rows = rows
        page.update()

    def add_fund(fund_name):
        if fund_name and fund_name not in added_funds:
            added_funds.append(fund_name)
            save_state()
            refresh_table()
        search_field.value = ""
        search_results_column.visible = False
        page.update()

    def update_search_suggestions(query):
        search_results_column.controls.clear()
        if query and len(query) >= 2:
            matches = [f for f in funds_list if query in f][:10]
            for match in matches:
                search_results_column.controls.append(
                    ft.ListTile(
                        title=ft.Text(match),
                        on_click=lambda e, m=match: add_fund(m)
                    )
                )
            search_results_column.visible = bool(matches)
        else:
            search_results_column.visible = False
        page.update()

    def remove_selected(e):
        selected_funds = [row.data for row in data_table.rows if row.selected]
        for f in selected_funds:
            if f in added_funds:
                added_funds.remove(f)
        save_state()
        refresh_table()

    def clear_table(e):
        added_funds.clear()
        invested_funds.clear()
        save_state()
        refresh_table()

    # משיכת נתונים ברקע
    def fetch_data_task():
        nonlocal df_clean, funds_list
        try:
            search_url = "https://data.gov.il/api/3/action/package_search?q=title:גמל-נט"
            res = requests.get(search_url).json()
            resource_id = "079cbab3-9c86-455b-b9d9-c454eefbebb6"
            
            if res.get('success') and res['result']['results']:
                resources = res['result']['results'][0]['resources']
                for r in resources:
                    if '2024' in r['name'] or '2025' in r['name'] or 'היום' in r['name']:
                        resource_id = r['id']
                        break
            
            url = f"https://data.gov.il/api/3/action/datastore_search?resource_id={resource_id}&limit=40000"
            data_res = requests.get(url).json()
            
            if data_res.get('success'):
                df = pd.DataFrame(data_res['result']['records'])
                df_clean = process_data(df)
                
                if not df_clean.empty:
                    funds_list = df_clean['שם ומספר מסלול'].dropna().astype(str).drop_duplicates().tolist()
                    status_text.value = "✅ הנתונים נטענו בהצלחה!"
                    status_text.color = ft.Colors.GREEN_700
                    search_field.disabled = False
                    
                    missing = [f for f in added_funds if f not in funds_list]
                    for m in missing:
                        added_funds.remove(m)
                        if m in invested_funds:
                            invested_funds.remove(m)
                            
                    save_state()
                    refresh_table()
                else:
                    status_text.value = "❌ לא נמצאו נתונים."
                    status_text.color = ft.Colors.RED_600
            else:
                status_text.value = "❌ נכשל ניסיון משיכת הנתונים מ-data.gov.il"
                status_text.color = ft.Colors.RED_600
        except Exception as e:
            status_text.value = f"❌ שגיאה: {str(e)}"
            status_text.color = ft.Colors.RED_600
        
        page.update()

    # עיצוב המסך הראשי
    page.add(
        ft.Column([
            ft.Text("📊 השוואת קופות גמל להשקעה", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("הנתונים נמשכים בזמן אמת ממאגרי משרד האוצר", size=14, color=ft.Colors.GREY_600),
            status_text,
            search_field,
            search_results_column,
            ft.Row([
                ft.ElevatedButton("➖ מחק נבחרים", on_click=remove_selected, bgcolor=ft.Colors.ORANGE_50, color=ft.Colors.ORANGE_900),
                ft.ElevatedButton("🗑️ נקה טבלה", on_click=clear_table, bgcolor=ft.Colors.RED_50, color=ft.Colors.RED_900)
            ], wrap=True),
            ft.Text("💡 טיפ: גלול ימינה ושמאלה לצפייה בטבלה. סמן שורה ולחץ 'מחק נבחרים' למחיקה. לחץ על הכוכב לסימון קופה מושקעת.", size=12, color=ft.Colors.GREY_500),
            table_container
        ], expand=True)
    )

    # התחלת טעינת נתונים
    threading.Thread(target=fetch_data_task, daemon=True).start()

if __name__ == '__main__':
    ft.app(target=main)
