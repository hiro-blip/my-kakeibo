import streamlit as st
import sqlite3
import pandas as pd
import datetime
import google.generativeai as genai
from PIL import Image
import json

# --- ページ設定 ---
st.set_page_config(
    page_title="Smart Budget",
    page_icon="💳",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- 【重要】APIキーの設定（Secretsから読み込む） ---
# GitHubにキーを公開しないための安全な書き方です
try:
    if "GEMINI_API_KEY" in st.secrets:
        API_KEY = st.secrets["GEMINI_API_KEY"]
    else:
        # ローカル（自分のPC）で動かす時用に、もしSecretsがなければ直接指定もできるようにしておく
        # ただし、GitHubに上げる時はここは空欄かダミーにしておくのが安全
        API_KEY = "ここには何も書かないか、ローカルテスト時のみ記述" 
        
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("APIキーの設定に失敗しました。StreamlitのSecretsを設定してください。")

# --- スタイル調整（無理な色指定を廃止し、余白のみ調整） ---
st.markdown("""
    <style>
    /* ボタンを少しリッチに */
    .stButton button {
        width: 100%;
        font-weight: bold;
        border-radius: 8px;
        height: 3em;
    }
    /* スマホでの入力欄の視認性向上 */
    div[data-testid="stInput"] {
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 1. データベース設定 ---
DB_NAME = 'kakeibo.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            category TEXT,
            item TEXT,
            amount INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS monthly_budgets (
            month TEXT,
            category TEXT,
            amount INTEGER,
            PRIMARY KEY (month, category)
        )
    ''')
    conn.commit()
    conn.close()

def add_expense(date, category, item, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO expenses (date, category, item, amount) VALUES (?, ?, ?, ?)',
              (date, category, item, amount))
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
    c.execute('INSERT OR REPLACE INTO monthly_budgets (month, category, amount) VALUES (?, ?, ?)',
              (month, category, amount))
    conn.commit()
    conn.close()

def get_monthly_budgets(month):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql('SELECT category, amount FROM monthly_budgets WHERE month = ?', conn, params=(month,))
    conn.close()
    if not df.empty:
        return df.set_index('category')['amount'].to_dict()
    return {}

init_db()

# --- カテゴリー一覧 ---
CATEGORIES = [
    "食費", "外食費", "日用品", "交通費", "家賃", "通信費(Wi-Fi)", "通信費(携帯)", 
    "ナッシュ", "Netflix", "Google One", "電気", "ガス", "水道", "電話代",
    "娯楽・趣味", "美容・衣類", "交際費", "医療費", "特別費", "その他"
]

# --- 2. AI解析 ---
def analyze_receipt(image):
    model = genai.GenerativeModel("gemini-flash-latest")
    categories_str = ", ".join([f'"{c}"' for c in CATEGORIES])
    prompt = f"""
    このレシート画像を解析して、以下の情報をJSON形式で抽出してください。
    【ルール】
    - 店名や品目から、リスト[{categories_str}]の中で最も適切なカテゴリを選んでください。
    - キーは "date", "amount", "item", "category"
    JSON以外の文字は不要です。
    """
    with st.spinner("AIが解析中..."):
        try:
            response = model.generate_content([prompt, image])
            text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except Exception as e:
            st.error(f"解析エラー: {e}")
            return None

# --- 3. メイン画面 ---
st.title("💳 Smart Budget")
st.caption("AI x Design Household Book")

# --- サイドバー ---
st.sidebar.title("Settings")
df_all = get_expenses()
if not df_all.empty:
    df_all["date"] = pd.to_datetime(df_all["date"])
    df_all["month_str"] = df_all["date"].dt.strftime("%Y年%m月")
    month_list = sorted(df_all["month_str"].unique(), reverse=True)
else:
    month_list = []
current_month = datetime.date.today().strftime("%Y年%m月")
if current_month not in month_list:
    month_list.insert(0, current_month)

selected_month = st.sidebar.selectbox("表示月", month_list)

# --- タブエリア ---
tab1, tab2 = st.tabs(["📝 入力 (Input)", "📊 分析 (Report)"])

# === タブ1：入力 ===
with tab1:
    # カード風コンテナ（ボーダー付き）で囲む
    with st.container(border=True):
        st.markdown("##### 📸 レシートスキャン")
        camera_file = st.camera_input("カメラを起動")
        upload_file = st.file_uploader("または画像を選択", type=["jpg", "png"])
        img_file = camera_file if camera_file else upload_file
        
        if img_file:
            image = Image.open(img_file)
            st.image(image, use_container_width=True)
            
            if st.button("AI解析スタート ✨", type="primary"):
                data = analyze_receipt(image)
                if data:
                    try:
                        try:
                            date_obj = datetime.datetime.strptime(data["date"], "%Y-%m-%d").date()
                        except:
                            date_obj = datetime.date.today()
                        
                        st.session_state["input_date"] = date_obj
                        st.session_state["input_amount"] = int(data["amount"])
                        st.session_state["input_item"] = data["item"]
                        
                        ai_cat = data.get("category", "その他")
                        if ai_cat not in CATEGORIES: ai_cat = "その他"
                        st.session_state["input_category"] = ai_cat
                        
                        st.success("解析完了！")
                        st.rerun()
                    except:
                        st.error("解析データの変換に失敗しました")

    st.markdown("<br>", unsafe_allow_html=True) # 余白

    with st.container(border=True):
        st.markdown("##### ✏️ 手動入力・修正")
        
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
            
            submit = st.form_submit_button("登録する ✅", type="primary")
            
            if submit:
                add_expense(date, category, item, amount)
                st.success("登録しました！")
                st.session_state["input_amount"] = 0
                st.session_state["input_item"] = ""

# === タブ2：分析 ===
with tab2:
    st.header(f"{selected_month}")
    
    if not df_all.empty:
        df_month = df_all[df_all["month_str"] == selected_month].copy()
    else:
        df_month = pd.DataFrame(columns=["category", "amount"])
    
    actual_sums = df_month.groupby("category")["amount"].sum().to_dict()
    budget_dict = get_monthly_budgets(selected_month)
    
    total_budget = sum(budget_dict.values())
    total_actual = sum(actual_sums.values())
    total_diff = total_budget - total_actual
    
    # 重要な数字をカードで表示
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        col1.metric("総予算", f"¥{total_budget:,}")
        col2.metric("総支出", f"¥{total_actual:,}")
        col3.metric("残り", f"¥{total_diff:,}", 
                    delta=f"{total_diff:,}円" if total_diff >= 0 else f"{total_diff:,}円",
                    delta_color="normal" if total_diff >= 0 else "inverse")
        
        if total_budget > 0:
            percent = min(total_actual / total_budget, 1.0)
            st.progress(percent)
            st.caption(f"予算消化率: {int(percent*100)}%")

    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.expander("⚙️ 予算設定 (Budget Config)"):
        edit_data = []
        for cat in CATEGORIES:
            edit_data.append({
                "項目": cat,
                "予算": budget_dict.get(cat, 0),
                "実績": actual_sums.get(cat, 0)
            })
        df_edit = pd.DataFrame(edit_data)
        edited_df = st.data_editor(
            df_edit,
            column_config={
                "項目": st.column_config.TextColumn(disabled=True),
                "予算": st.column_config.NumberColumn(format="¥%d", min_value=0),
                "実績": st.column_config.NumberColumn(format="¥%d", disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic"
        )
        if st.button("予算を保存", type="primary"):
            for index, row in edited_df.iterrows():
                set_category_budget(selected_month, row["項目"], row["予算"])
            st.success("保存しました！")
            st.rerun()

    st.subheader("Details")
    if not df_month.empty:
        report_data = []
        for cat in CATEGORIES:
            b = budget_dict.get(cat, 0)
            a = actual_sums.get(cat, 0)
            if b == 0 and a == 0: continue
            report_data.append({"項目":cat, "予算":b, "実績":a, "残高":b-a})
        
        if report_data:
            df_report = pd.DataFrame(report_data)
            # 数値フォーマットのみ適用（色付けはCSS競合を避けるためシンプルに）
            st.dataframe(
                df_report.style.format({
                    "予算": "¥{:,.0f}", 
                    "実績": "¥{:,.0f}", 
                    "残高": "¥{:,.0f}"
                }),
                use_container_width=True, hide_index=True
            )
        
        with st.expander("🗑️ 履歴の確認・削除"):
            df_hist = df_month.sort_values("date", ascending=False)
            st.dataframe(df_hist[["date", "category", "item", "amount"]], use_container_width=True)
            
            opts = {f"{r['date']} {r['item']} ¥{r['amount']}": r['id'] for i,r in df_hist.iterrows()}
            dels = st.multiselect("削除データ選択", list(opts.keys()))
            if st.button("削除実行"):
                for label in dels: delete_expense(opts[label])
                st.success("削除しました")
                st.rerun()
