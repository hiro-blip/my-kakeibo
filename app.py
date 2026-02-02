import streamlit as st
import sqlite3
import pandas as pd
import datetime
import google.generativeai as genai
from PIL import Image
import json
import time

# --- ページ設定 ---
st.set_page_config(
    page_title="Smart Budget",
    page_icon="💳",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- APIキーの設定（Secrets対応） ---
try:
    if "GEMINI_API_KEY" in st.secrets:
        API_KEY = st.secrets["GEMINI_API_KEY"]
    else:
        # Secretsがない場合（ローカルテスト用など）
        # ここに直接キーを入れても動きますが、Github公開時は注意してください
        API_KEY = "ここにAPIキーを貼り付け" 
        
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("APIキーの設定に失敗しました。")

# --- CSS ---
st.markdown("""
    <style>
    .stButton button { width: 100%; font-weight: bold; height: 3em; }
    div[data-testid="stInput"] { border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# --- データベース ---
DB_NAME = 'kakeibo.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT, item TEXT, amount INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS monthly_budgets (month TEXT, category TEXT, amount INTEGER, PRIMARY KEY (month, category))')
    conn.commit()
    conn.close()

def add_expense(date, category, item, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO expenses (date, category, item, amount) VALUES (?, ?, ?, ?)', (date, category, item, amount))
    conn.commit()
    conn.close()

def get_expenses():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql('SELECT * FROM expenses', conn)
    conn.close()
    return df

def delete_expense(expense_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM expenses WHERE id = ?', (expense_id,))
    conn.commit()
    conn.close()

def set_category_budget(month, category, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO monthly_budgets (month, category, amount) VALUES (?, ?, ?)', (month, category, amount))
    conn.commit()
    conn.close()

def get_monthly_budgets(month):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql('SELECT category, amount FROM monthly_budgets WHERE month = ?', conn, params=(month,))
    conn.close()
    if not df.empty: return df.set_index('category')['amount'].to_dict()
    return {}

init_db()

CATEGORIES = [
    "食費", "外食費", "日用品", "交通費", "家賃", "通信費(Wi-Fi)", "通信費(携帯)", 
    "ナッシュ", "Netflix", "Google One", "電気", "ガス", "水道", "電話代",
    "娯楽・趣味", "美容・衣類", "交際費", "医療費", "特別費", "その他"
]

# --- 【修正版】AI解析関数 ---
def analyze_receipt(image):
    # ★絶対に軽いモデルを使う
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    categories_str = ", ".join([f'"{c}"' for c in CATEGORIES])
    prompt = f"""
    このレシート画像を解析してJSONのみを出力してください。
    キー: "date", "amount", "item", "category"
    カテゴリー候補: [{categories_str}]
    """
    
    # ★画像を強制的に小さくする（幅600px）
    img_resized = image.copy()
    img_resized.thumbnail((600, 600))
    
    st.write("🔄 画像を圧縮しました。AIに送信します...") # デバッグ表示
    
    try:
        response = model.generate_content([prompt, img_resized])
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"解析エラー: {e}")
        return None

# --- メイン画面 ---
st.title("💳 Smart Budget")

# サイドバー
st.sidebar.title("Settings")
df_all = get_expenses()
if not df_all.empty:
    df_all["date"] = pd.to_datetime(df_all["date"])
    df_all["month_str"] = df_all["date"].dt.strftime("%Y年%m月")
    month_list = sorted(df_all["month_str"].unique(), reverse=True)
else:
    month_list = []
current_month = datetime.date.today().strftime("%Y年%m月")
if current_month not in month_list: month_list.insert(0, current_month)
selected_month = st.sidebar.selectbox("表示月", month_list)

tab1, tab2 = st.tabs(["📝 入力", "📊 分析"])

with tab1:
    with st.container(border=True):
        st.markdown("##### 📸 レシートスキャン")
        camera_file = st.camera_input("カメラを起動")
        upload_file = st.file_uploader("画像を選択", type=["jpg", "png"])
        img_file = camera_file if camera_file else upload_file
        
        if img_file:
            image = Image.open(img_file)
            st.image(image, use_container_width=True)
            
            if st.button("AI解析スタート 🚀", type="primary"):
                with st.spinner("AIが高速解析中..."):
                    data = analyze_receipt(image)
                    if data:
                        try:
                            try: date_obj = datetime.datetime.strptime(data["date"], "%Y-%m-%d").date()
                            except: date_obj = datetime.date.today()
                            
                            st.session_state["input_date"] = date_obj
                            st.session_state["input_amount"] = int(data["amount"])
                            st.session_state["input_item"] = data["item"]
                            ai_cat = data.get("category", "その他")
                            if ai_cat not in CATEGORIES: ai_cat = "その他"
                            st.session_state["input_category"] = ai_cat
                            
                            st.success("完了！登録ボタンを押してください")
                            st.rerun()
                        except:
                            st.error("データの形式エラー")

    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("##### ✏️ 手動入力")
        if "input_date" not in st.session_state: st.session_state["input_date"] = datetime.date.today()
        if "input_amount" not in st.session_state: st.session_state["input_amount"] = 0
        if "input_item" not in st.session_state: st.session_state["input_item"] = ""
        if "input_category" not in st.session_state: st.session_state["input_category"] = "食費"
        
        with st.form("input_form", clear_on_submit=True):
            date = st.date_input("日付", value=st.session_state["input_date"])
            amount = st.number_input("金額 (¥)", min_value=0, step=1, value=st.session_state["input_amount"])
            try: idx = CATEGORIES.index(st.session_state["input_category"])
            except: idx = 0
            category = st.selectbox("カテゴリー", CATEGORIES, index=idx)
            item = st.text_input("品目・メモ", value=st.session_state["input_item"])
            
            if st.form_submit_button("登録する ✅", type="primary"):
                add_expense(date, category, item, amount)
                st.success("登録しました")
                st.session_state["input_amount"] = 0
                st.session_state["input_item"] = ""

with tab2:
    st.header(f"{selected_month}")
    if not df_all.empty: df_month = df_all[df_all["month_str"] == selected_month].copy()
    else: df_month = pd.DataFrame(columns=["category", "amount"])
    
    actual_sums = df_month.groupby("category")["amount"].sum().to_dict()
    budget_dict = get_monthly_budgets(selected_month)
    total_budget = sum(budget_dict.values())
    total_actual = sum(actual_sums.values())
    total_diff = total_budget - total_actual
    
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        col1.metric("予算", f"¥{total_budget:,}")
        col2.metric("支出", f"¥{total_actual:,}")
        col3.metric("残り", f"¥{total_diff:,}", delta=f"{total_diff:,}", delta_color="normal" if total_diff >= 0 else "inverse")
        if total_budget > 0: st.progress(min(total_actual / total_budget, 1.0))
    
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("⚙️ 予算設定"):
        edit_data = [{"項目": c, "予算": budget_dict.get(c, 0), "実績": actual_sums.get(c, 0)} for c in CATEGORIES]
        edited_df = st.data_editor(pd.DataFrame(edit_data), use_container_width=True, hide_index=True)
        if st.button("予算保存"):
            for i, r in edited_df.iterrows(): set_category_budget(selected_month, r["項目"], r["予算"])
            st.success("保存しました")
            st.rerun()

    st.subheader("詳細リスト")
    if not df_month.empty:
        report_data = [{"項目":c, "予算":budget_dict.get(c,0), "実績":actual_sums.get(c,0), "残高":budget_dict.get(c,0)-actual_sums.get(c,0)} for c in CATEGORIES if budget_dict.get(c,0)!=0 or actual_sums.get(c,0)!=0]
        if report_data: st.dataframe(pd.DataFrame(report_data).style.format({"予算":"¥{:,.0f}","実績":"¥{:,.0f}","残高":"¥{:,.0f}"}), use_container_width=True, hide_index=True)
        
        with st.expander("🗑️ 削除"):
            df_hist = df_month.sort_values("date", ascending=False)
            opts = {f"{r['date']} {r['item']} ¥{r['amount']}": r['id'] for i,r in df_hist.iterrows()}
            dels = st.multiselect("削除データ", list(opts.keys()))
            if st.button("削除実行"):
                for l in dels: delete_expense(opts[l])
                st.rerun()
