import sys
import os
import json
import threading
import requests
import pandas as pd
import flet as ft

# חיפוש חכם של תיקייה מורשית כתיבה באנדרואיד
def get_safe_storage_path():
    candidates = [
        os.environ.get("HOME", ""),
        os.environ.get("TMPDIR", ""),
        os.path.expanduser("~"),
        "/storage/emulated/0/Download", 
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd()
    ]

    for path in candidates:
        if not path: 
            continue
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)

            test_file = os.path.join(path, ".test_write")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            return os.path.join(path, "gedroeid_save_data.json")
        except Exception:
            continue

    return "gedroeid_save_data.json"

SAVE_FILE = get_safe_storage_path()

def safe_to_float(value):
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
    if df.empty:
        return df

    df.columns = [str(col).upper() for col in df.columns]
    original_df = df.copy()

    id_col = 'FUND_ID' if 'FUND_ID' in df.columns else 'ID'
    name_col = 'FUND_NAME' if 'FUND_NAME' in df.columns else 'NAME'

    if name_col in df.columns:
        name_text = df[name_col].astype(str)
        investment_mask = name_text.str.contains('להשקעה', na=False, regex=False)
        altshuler_saving_mask = (
            name_text.str.contains('אלטשולר', na=False, regex=False) &
            name_text.str.contains('חיסכון', na=False, regex=False)
        )
        df = df[investment_mask | altshuler_saving_mask]

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

    avg_annual_returns = []
    for _, row in output.iterrows():
        v_5y = safe_to_float(row.get('תשואה 5 שנים'))
        v_3y = safe_to_float(row.get('תשואה 3 שנים'))

        if v_5y is not None:
            annualized = ((1.0 + v_5y / 100.0) ** (1.0 / 5.0) - 1.0) * 100.0
        elif v_3y is not None:
            annualized = ((1.0 + v_3y / 100.0) ** (1.0 / 3.0) - 1.0) * 100.0
        else:
            annualized = None

        avg_annual_returns.append(annualized)

    output['תשואה שנתית ממוצעת (3/5 שנים)'] = avg_annual_returns

    df_clean = output
    if 'שם ומספר מסלול' in df_clean.columns:
        df_clean = df_clean.drop_duplicates(subset=['שם ומספר מסלול'], keep='first')

    return df_clean

def main(page: ft.Page):
    page.title = "השוואת קופות גמל להשקעה"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    local_state = {}
    try:
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                local_state = json.load(f)
    except Exception:
        pass

    df_clean = pd.DataFrame()
    added_funds = local_state.get("added_funds", [])
    invested_funds = set(local_state.get("invested_funds", []))
    funds_list = []

    sort_column_idx = local_state.get("sort_column_idx", 1)
    sort_ascending = local_state.get("sort_ascending", False)

    status_text = ft.Text("⏳ מוריד נתונים עדכניים ממשרד האוצר... אנא המתן.", color=ft.Colors.ORANGE_700, weight=ft.FontWeight.BOLD)
    debug_text = ft.Text(f"מצב שמירה: ממתין לשינויים... ({SAVE_FILE})", size=10, color=ft.Colors.GREY_400)

    search_field = ft.TextField(
        label="הקלד שם מסלול או מספר קופה...",
        on_change=lambda e: update_search_suggestions(e.control.value),
        disabled=True,
        expand=True
    )

    search_results_column = ft.Column(visible=False)

    horizon_dropdown = ft.Dropdown(
        label="טווח השקעה מתוכנן",
        options=[
            ft.dropdown.Option("קצר (עד 3 שנים)"), 
            ft.dropdown.Option("בינוני (3-5 שנים)"), 
            ft.dropdown.Option("ארוך (5+ שנים)")
        ],
        value=local_state.get("horizon", "בינוני (3-5 שנים)"),
        expand=True
    )

    risk_dropdown = ft.Dropdown(
        label="רמת סיכון מועדפת",
        options=[
            ft.dropdown.Option("סולידי (סיכון נמוך)"), 
            ft.dropdown.Option("מאוזן (סיכון בינוני)"), 
            ft.dropdown.Option("אגרסיבי (סיכון גבוה)")
        ],
        value=local_state.get("risk", "מאוזן (סיכון בינוני)"),
        expand=True
    )

    advisor_text = ft.Text("הוסף קופות לטבלה כדי לקבל המלצה חכמה.", color=ft.Colors.BLUE_700, weight=ft.FontWeight.BOLD)

    advisor_card = ft.Card(
        elevation=2,
        content=ft.Container(
            padding=15,
            bgcolor=ft.Colors.BLUE_50,
            content=ft.Column([
                ft.Text("🤖 יועץ השקעות אישי", weight=ft.FontWeight.BOLD, size=18, color=ft.Colors.BLUE_900),
                ft.Text("בחר את הפרופיל שלך והמערכת תחשב 'ציון חכם' (0-100) לכל קופה בטבלה:", size=13),
                ft.Row([horizon_dropdown, risk_dropdown]),
                advisor_text
            ])
        )
    )

    col_specs = [
        ('שם ומספר מסלול', False),
        ('ציון חכם', False),
        ('תשואה חודש אחרון', True),
        ('תשואה 12 חודשים אחרונים', True),
        ('תשואה שנה אחרונה', True),
        ('תשואה 3 שנים', True),
        ('תשואה 5 שנים', True),
        ('תשואה שנתית ממוצעת (3/5 שנים)', True),
        ('מדד שארפ', False),
        ('מושקע', False) 
    ]

    def save_state():
        state_dict = {
            "added_funds": added_funds,
            "invested_funds": list(invested_funds),
            "sort_column_idx": sort_column_idx,
            "sort_ascending": sort_ascending,
            "horizon": horizon_dropdown.value,
            "risk": risk_dropdown.value
        }
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, ensure_ascii=False)
            debug_text.value = f"✅ נשמר בהצלחה בנתיב: {SAVE_FILE}"
            debug_text.color = ft.Colors.GREY_400
        except Exception as e:
            debug_text.value = f"❌ שגיאת הרשאות כתיבה לאנדרואיד: {str(e)}"
            debug_text.color = ft.Colors.RED_500
        page.update()

    def update_profile():
        save_state()
        refresh_table()

    horizon_dropdown.on_change = lambda e: update_profile()
    risk_dropdown.on_change = lambda e: update_profile()

    # --- מנגנון בחירה ומחיקה חכם ---
    delete_btn = ft.ElevatedButton("➖ בחר מסלולים למחיקה", bgcolor=ft.Colors.ORANGE_50, color=ft.Colors.ORANGE_900)
    cancel_delete_btn = ft.ElevatedButton("❌ ביטול מצב מחיקה", bgcolor=ft.Colors.GREY_200, color=ft.Colors.BLACK, visible=False)

    def on_delete_btn_click(e):
        if not data_table.show_checkbox_column:
            data_table.show_checkbox_column = True
            delete_btn.text = "⏳ ממתין לבחירת מסלולים..."
            cancel_delete_btn.visible = True
            page.update()
        else:
            selected_funds = [row.data for row in data_table.rows if row.selected]
            if selected_funds:
                for f in selected_funds:
                    if f in added_funds:
                        added_funds.remove(f)
                    if f in invested_funds:
                        invested_funds.remove(f)
                save_state()

            data_table.show_checkbox_column = False
            delete_btn.text = "➖ בחר מסלולים למחיקה"
            cancel_delete_btn.visible = False
            refresh_table()

    def on_cancel_delete_click(e):
        data_table.show_checkbox_column = False
        delete_btn.text = "➖ בחר מסלולים למחיקה"
        cancel_delete_btn.visible = False
        for row in data_table.rows:
            row.selected = False
        page.update()

    def on_row_select(e):
        # טיפול קשיח בערך הבוליאני שמגיע מ-Flet באנדרואיד כדי למנוע קריאה שגויה של הסטטוס
        is_selected = str(e.data).lower() in ["true", "1", "t", "yes"]
        e.control.selected = is_selected

        selected_count = sum(1 for row in data_table.rows if row.selected)
        if selected_count > 0:
            delete_btn.text = "🗑️ מחק מסלולים נבחרים"
        else:
            delete_btn.text = "⏳ ממתין לבחירת מסלולים..."
        page.update()

    delete_btn.on_click = on_delete_btn_click
    cancel_delete_btn.on_click = on_cancel_delete_click

    # --- מנגנון יצוא ויבוא ---
    def export_to_downloads(e):
        try:
            download_dir = "/storage/emulated/0/Download"
            if not os.path.exists(download_dir):
                download_dir = os.path.expanduser("~") 

            backup_path = os.path.join(download_dir, "gedroeid_backup.json")
            state_dict = {
                "added_funds": added_funds,
                "invested_funds": list(invested_funds),
                "sort_column_idx": sort_column_idx,
                "sort_ascending": sort_ascending,
                "horizon": horizon_dropdown.value,
                "risk": risk_dropdown.value
            }
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, ensure_ascii=False)

            status_text.value = f"✅ הגדרות גובו בהצלחה לתיקיית ההורדות (Download)!"
            status_text.color = ft.Colors.GREEN_700
        except Exception as ex:
            status_text.value = f"❌ שגיאה ביצוא: {str(ex)}"
            status_text.color = ft.Colors.RED_600
        page.update()

    def on_import_result(e: ft.FilePickerResultEvent):
        if e.files and len(e.files) > 0:
            try:
                with open(e.files[0].path, "r", encoding="utf-8") as f:
                    imported_state = json.load(f)

                nonlocal sort_column_idx, sort_ascending
                added_funds.clear()
                added_funds.extend(imported_state.get("added_funds", []))
                invested_funds.clear()
                invested_funds.update(imported_state.get("invested_funds", []))

                sort_column_idx = imported_state.get("sort_column_idx", sort_column_idx)
                sort_ascending = imported_state.get("sort_ascending", sort_ascending)

                if "horizon" in imported_state:
                    horizon_dropdown.value = imported_state["horizon"]
                if "risk" in imported_state:
                    risk_dropdown.value = imported_state["risk"]

                save_state()
                refresh_table()

                status_text.value = "✅ ההגדרות יובאו בהצלחה!"
                status_text.color = ft.Colors.GREEN_700
            except Exception as ex:
                status_text.value = f"❌ שגיאה ביבוא: {str(ex)}"
                status_text.color = ft.Colors.RED_600
            page.update()

    # יצירת ה-FilePicker והשמת on_result בשורה נפרדת למניעת שגיאת unexpected keyword argument
    import_picker = ft.FilePicker()
    import_picker.on_result = on_import_result
    
    page.overlay.append(import_picker)

    def on_sort(e: ft.DataColumnSortEvent):
        nonlocal sort_column_idx, sort_ascending
        sort_column_idx = e.column_index
        sort_ascending = e.ascending
        save_state()
        refresh_table()

    columns = []
    for i, (col_name, _) in enumerate(col_specs):
        columns.append(
            ft.DataColumn(
                ft.Text(col_name, weight=ft.FontWeight.BOLD),
                on_sort=on_sort if i < 9 else None
            )
        )

    data_table = ft.DataTable(
        columns=columns,
        show_checkbox_column=False, 
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

        valid_funds = [f for f in added_funds if not df_clean[df_clean['שם ומספר מסלול'] == f].empty]

        stats = {}
        for col_name, _ in col_specs:
            if col_name in ['שם ומספר מסלול', 'מושקע', 'ציון חכם']: continue
            vals = [safe_to_float(df_clean[df_clean['שם ומספר מסלול'] == f].iloc[0].get(col_name)) for f in valid_funds]
            vals = [v for v in vals if v is not None]
            if vals:
                stats[col_name] = {'min': min(vals), 'max': max(vals), 'avg': sum(vals)/len(vals)}
            else:
                stats[col_name] = {'min': 0, 'max': 0, 'avg': 0}

        def get_winner(col, require_positive=False):
            if not valid_funds: return None
            best_f, max_v = None, -9999
            for f in valid_funds:
                v = safe_to_float(df_clean[df_clean['שם ומספר מסלול'] == f].iloc[0].get(col))
                if v is not None and v > max_v:
                    max_v = v; best_f = f
            if require_positive and max_v <= 0:
                return None
            return best_f

        winners = {
            'king': get_winner('תשואה 5 שנים', require_positive=True) or get_winner('תשואה 3 שנים', require_positive=True),
            'stable': get_winner('מדד שארפ'),
            'rocket': get_winner('תשואה חודש אחרון', require_positive=True)
        }

        h_val, r_val = horizon_dropdown.value, risk_dropdown.value
        w_12m, w_3y, w_5y, w_sharpe = 0.1, 0.4, 0.3, 0.2

        if "קצר" in h_val: w_12m, w_3y, w_5y = 0.4, 0.4, 0.0
        elif "ארוך" in h_val: w_12m, w_3y, w_5y = 0.0, 0.3, 0.5

        if "סולידי" in r_val:
            w_sharpe += 0.3; w_12m = max(0, w_12m-0.1); w_3y = max(0, w_3y-0.1); w_5y = max(0, w_5y-0.1)
        elif "אגרסיבי" in r_val:
            w_sharpe = 0.0; w_12m += 0.05; w_3y += 0.1; w_5y += 0.05

        total_w = w_12m + w_3y + w_5y + w_sharpe
        if total_w > 0: w_12m /= total_w; w_3y /= total_w; w_5y /= total_w; w_sharpe /= total_w

        scores = {}
        for f in valid_funds:
            score = 0
            def norm(val, stat):
                if val is None or stat['max'] == stat['min']: return 50
                return 100 * (val - stat['min']) / (stat['max'] - stat['min'])

            row = df_clean[df_clean['שם ומספר מסלול'] == f].iloc[0]
            v_12m = safe_to_float(row.get('תשואה 12 חודשים אחרונים'))
            v_3y = safe_to_float(row.get('תשואה 3 שנים'))
            v_5y = safe_to_float(row.get('תשואה 5 שנים'))
            v_sh = safe_to_float(row.get('מדד שארפ'))

            score += w_12m * norm(v_12m, stats.get('תשואה 12 חודשים אחרונים', {'min':0, 'max':0}))
            score += w_3y * norm(v_3y, stats.get('תשואה 3 שנים', {'min':0, 'max':0}))
            score += w_5y * norm(v_5y, stats.get('תשואה 5 שנים', {'min':0, 'max':0}))
            score += w_sharpe * norm(v_sh, stats.get('מדד שארפ', {'min':0, 'max':0}))
            scores[f] = score

        if scores:
            best_f = max(scores, key=scores.get)
            advisor_text.value = f"🎯 המסלול המומלץ ביותר עבורך: {best_f} (ציון: {scores[best_f]:.0f}/100)"
            advisor_text.color = ft.Colors.GREEN_700
        else:
            advisor_text.value = "הוסף קופות לטבלה כדי לקבל המלצה חכמה."
            advisor_text.color = ft.Colors.BLUE_700

        sort_col_name = col_specs[sort_column_idx][0]

        def get_sort_val(fund_name):
            if sort_col_name == 'ציון חכם': return scores.get(fund_name, -999.0)
            if sort_col_name == 'מושקע': return 1 if fund_name in invested_funds else 0

            row = df_clean[df_clean['שם ומספר מסלול'] == fund_name]
            if row.empty: return -999.0
            val = safe_to_float(row.iloc[0].get(sort_col_name))
            return val if val is not None else -999.0

        sorted_funds = sorted(added_funds, key=get_sort_val, reverse=not sort_ascending)

        current_selected = set()
        if data_table.rows:
            current_selected = {row.data for row in data_table.rows if row.selected}

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

                if col_name == 'ציון חכם':
                    sc = scores.get(fund_name, 0)
                    color = ft.Colors.GREEN_600 if sc >= 80 else ft.Colors.ORANGE_600 if sc >= 50 else ft.Colors.RED_600
                    cells.append(ft.DataCell(ft.Text(f"{sc:.0f}", color=color, weight=ft.FontWeight.BOLD)))
                    continue

                if col_name == 'שם ומספר מסלול':
                    badges = []
                    if fund_name == winners['king']: badges.append("🌟")
                    if fund_name == winners['stable']: badges.append("🛡️")
                    if fund_name == winners['rocket']: badges.append("🚀")
                    disp = fund_name + (" " + "".join(badges) if badges else "")
                    cells.append(ft.DataCell(ft.Text(disp, width=200)))
                    continue

                val = fund_row.get(col_name, None)
                num_val = safe_to_float(val)

                if num_val is None:
                    cells.append(ft.DataCell(ft.Text("---", color=ft.Colors.BLACK)))
                else:
                    avg = stats.get(col_name, {}).get('avg', None)
                    is_above_avg = avg is not None and num_val > avg
                    is_below_avg = avg is not None and num_val < avg

                    display_text = f"{num_val:.2f}%" if is_percent else f"{num_val:.2f}"

                    if len(valid_funds) > 1:
                        if is_above_avg:
                            display_text += " ▲"
                            text_color = ft.Colors.GREEN_600
                        elif is_below_avg:
                            display_text += " ▼"
                            text_color = ft.Colors.RED_600
                        else:
                            text_color = ft.Colors.BLACK
                    else:
                        text_color = ft.Colors.GREEN_600 if num_val > 0 else ft.Colors.RED_600 if num_val < 0 else ft.Colors.BLACK

                    cells.append(ft.DataCell(ft.Text(display_text, color=text_color)))

            row_color = ft.Colors.GREEN_50 if fund_name in invested_funds else ft.Colors.TRANSPARENT
            rows.append(ft.DataRow(
                cells=cells, 
                data=fund_name, 
                color=row_color,
                selected=(fund_name in current_selected),
                on_select_changed=on_row_select
            ))

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

    def clear_table(e):
        added_funds.clear()
        invested_funds.clear()
        save_state()
        data_table.show_checkbox_column = False
        delete_btn.text = "➖ בחר מסלולים למחיקה"
        cancel_delete_btn.visible = False
        refresh_table()

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

    legend_text = ft.Text("מקרא תגים: 🌟 מלך הביצועים (3/5 שנים) | 🛡️ הכי יציבה (שארפ) | 🚀 צומחת (חודש אחרון) | ▲/▼ מעל/מתחת לממוצע", size=11, color=ft.Colors.GREY_600)

    page.add(
        ft.Column([
            ft.Text("📊 השוואת קופות גמל להשקעה", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("הנתונים נמשכים בזמן אמת ממאגרי משרד האוצר", size=14, color=ft.Colors.GREY_600),
            status_text,
            advisor_card,
            search_field,
            search_results_column,
            ft.Row([
                delete_btn,
                cancel_delete_btn,
                ft.ElevatedButton("🗑️ נקה טבלה", on_click=clear_table, bgcolor=ft.Colors.RED_50, color=ft.Colors.RED_900),
                ft.ElevatedButton("📤 יצוא ל-Download", on_click=export_to_downloads, bgcolor=ft.Colors.BLUE_50, color=ft.Colors.BLUE_900),
                ft.ElevatedButton("📥 יבוא הגדרות", on_click=lambda _: import_picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["json"]), bgcolor=ft.Colors.BLUE_50, color=ft.Colors.BLUE_900)
            ], wrap=True),
            legend_text,
            table_container,
            debug_text
        ], expand=True)
    )

    threading.Thread(target=fetch_data_task, daemon=True).start()

if __name__ == '__main__':
    ft.app(target=main)
