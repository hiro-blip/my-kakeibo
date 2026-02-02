import streamlit as st
import sqlite3
import pandas as pd
import datetime
import google.generativeai as genai
from PIL import Image
import json
import time
import re
import io

# --- ページ設定 ---
st.set_page_config(
    page_title="Smart Budget Pro",
    page_icon="💳",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- APIキーの設定 ---
try:
    if "GEMINI_API_KEY" in st.secrets:
        API_KEY = st.secrets["GEMINI_API_KEY"].strip()
        genai.configure(api_key=API_KEY)
    else:
        st.error("APIキー未設定: Secretsを設定してください")
except Exception as e:
    st.error(f"API設定エラー: {e}")

# --- CSS (デザイン) ---
st.markdown("""
    <style>
    .stButton button { width: 100%; font-weight: bold; height: 3em; }
    div[data-testid="stInput"] { border-radius: 8px; }
    /* 成功メッセージを派手に */
    .success-msg { color: #155724; background-color: #d4edda; padding: 10px; border-radius: 5px; text-align: center; }
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

# ★新機能：CSVからデータを復元
def restore_from_csv(file):
    try:
        df = pd.read_csv(file)
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # 既存データの重複を防ぐため、単純な追記にするか、全削除して入れ替えるか選べますが、
        # 安全のため「追記」にします（同じデータを読み込むと重複します）
        for _, row in df.iterrows():
            c.execute('INSERT INTO expenses (date, category, item, amount) VALUES (?, ?, ?, ?)',
                      (row['date'], row['category'], row['item'], row['amount']))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return False

init_db()

CATEGORIES = [
    "食費", "外食費", "日用品", "交通費", "家賃", "通信費(Wi-Fi)", "通信費(携帯)", 
    "ナッシュ", "Netflix", "Google One", "電気", "ガス", "水道", "電話代",
    "娯楽・趣味", "美容・衣類", "交際費", "医療費", "特別費", "その他"
]

# ★あなたの固定費リスト（スプレッドシートから転記）
FIXED_COSTS = [
    {"category": "家賃", "item": "家賃", "amount": 60700},
    {"category": "通信費(Wi-Fi)", "item": "Wi-Fi代", "amount": 4433},
    {"category": "通信費(携帯)", "item": "携帯代", "amount": 2983},
    {"category": "ナッシュ", "item": "nosh定期便", "amount": 6372},
    {"category": "Netflix", "item": "Netflix月額", "amount": 890},
    {"category": "Google One", "item": "Gemini Advanced", "amount": 2900}
]

# --- AI解析 ---
def analyze_receipt(image):
    model = genai.GenerativeModel("gemini-flash-latest")
    categories_str = ", ".join([f'"{c}"' for c in CATEGORIES])
    prompt = f"""
    このレシート画像を解析して以下のJSONのみ出力せよ。
    {{ "date": "YYYY-MM-DD", "amount": 0, "item": "品目", "category": "カテゴリ" }}
    カテゴリ候補: [{categories_str}]
    """
    img_resized = image.copy()
    img_resized.thumbnail((600, 600))
    st.write("🔄 AI解析中...")
    try:
        response = model.generate_content([prompt, img_resized], request_options={"timeout": 15})
        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        if match: return json.loads(match.group(0))
    except: pass
    return None

# --- メイン画面 ---
st.title("💳 Smart Budget Pro")

# サイドバー設定
st.sidebar.title("🛠️ 設定・管理")
df_all = get_expenses()
if not df_all.empty:
    df_all["date"] = pd.to_datetime(df_all["date"])
    df_all["month_str"] = df_all["date"].dt.strftime("%Y年%m月")
    month_list = sorted(df_all["month_str"].unique(), reverse=True)
else:
    month_list = []
current_month_str = datetime.date.today().strftime("%Y年%m月")
if current_month_str not in month_list: month_list.insert(0, current_month_str)

selected_month = st.sidebar.selectbox("表示月", month_list)

# ★新機能：バックアップエリア（サイドバー）
st.sidebar.markdown("---")
st.sidebar.subheader("💾 データ管理")
# ダウンロード
if not df_all.empty:
    csv = df_all.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="データを保存 (CSV)",
        data=csv,
        file_name='kakeibo_backup.csv',
        mime='text/csv',
    )
# 復元
uploaded_backup = st.sidebar.file_uploader("データを復元 (CSV)", type=['csv'])
if uploaded_backup is not None:
    if st.sidebar.button("復元を実行"):
        if restore_from_csv(uploaded_backup):
            st.sidebar.success("復元しました！")
            time.sleep(1)
            st.rerun()
        else:
            st.sidebar.error("復元に失敗しました")

# メインタブ
tab1, tab2, tab3 = st.tabs(["📝 入力", "⚡ 固定費", "📊 分析"])

# --- TAB 1: 通常入力 ---
with tab1:
    with st.container(border=True):
        st.markdown("##### 📸 レシートスキャン")
        img_file = st.camera_input("カメラ") or st.file_uploader("画像選択", type=["jpg", "png"])
        if img_file and st.button("AI解析 🚀", type="primary"):
            data = analyze_receipt(Image.open(img_file))
            if data:
                try:
                    d = datetime.datetime.strptime(data["date"], "%Y-%m-%d").date()
                    st.session_state.update({"input_date": d, "input_amount": int(data["amount"]), "input_item": data["item"], "input_category": data.get("category", "その他")})
                    st.success("解析完了！登録してください")
                    time.sleep(1)
                    st.rerun()
                except: st.error("データ変換エラー")
            else: st.error("読み取り失敗")

    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("##### ✏️ 手動入力")
        # セッション初期化
        for k, v in {"input_date": datetime.date.today(), "input_amount": 0, "input_item": "", "input_category": "食費"}.items():
            if k not in st.session_state: st.session_state[k] = v
            
        with st.form("input"):
            d = st.date_input("日付", st.session_state.input_date)
            a = st.number_input("金額", value=st.session_state.input_amount, step=1)
            c = st.selectbox("カテゴリ", CATEGORIES, index=CATEGORIES.index(st.session_state.input_category) if st.session_state.input_category in CATEGORIES else 0)
            i = st.text_input("品目", st.session_state.input_item)
            if st.form_submit_button("登録 ✅", type="primary"):
                add_expense(d, c, i, a)
                st.success("登録しました")
                # 入力欄リセット
                st.session_state.update({"input_amount": 0, "input_item": ""})
                time.sleep(1)
                st.rerun()

# --- TAB 2: 固定費一括登録 ---
with tab2:
    st.header("⚡ 固定費の一括登録")
    st.caption("毎月決まった支払いを、ボタン一つで登録します。")
    
    # 今月の固定費リストを表示
    fixed_df = pd.DataFrame(FIXED_COSTS)
    st.dataframe(fixed_df.style.format({"amount": "¥{:,}"}), use_container_width=True, hide_index=True)
    
    target_date = st.date_input("登録する日付", value=datetime.date.today().replace(day=25)) # 給料日付近をデフォルトに
    
    if st.button(f"{target_date.strftime('%Y年%m月')}分として登録する 💰", type="primary"):
        count = 0
        total_fixed = 0
        for cost in FIXED_COSTS:
            add_expense(target_date, cost['category'], cost['item'], cost['amount'])
            count += 1
            total_fixed += cost['amount']
        
        st.balloons() # 派手な演出
        st.success(f"{count}件（合計 ¥{total_fixed:,}）を登録しました！")
        time.sleep(2)
        st.rerun()

# --- TAB 3: 分析 ---
with tab3:
    st.header(f"{selected_month}")
    if not df_all.empty: df_month = df_all[df_all["month_str"] == selected_month].copy()
    else: df_month = pd.DataFrame(columns=["category", "amount"])
    
    actual = df_month.groupby("category")["amount"].sum().to_dict()
    budget = get_monthly_budgets(selected_month)
    
    # 予算自動セット（なければヒントを表示）
    if not budget:
        st.info("💡 下の「予算設定」で予算を決めると、使いすぎ防止メーターが表示されます。")

    t_budget, t_actual = sum(budget.values()), sum(actual.values())
    diff = t_budget - t_actual
    
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("予算", f"¥{t_budget:,}")
        c2.metric("支出", f"¥{t_actual:,}")
        c3.metric("残り", f"¥{diff:,}", delta=f"{diff:,}", delta_color="normal" if diff >= 0 else "inverse")
        if t_budget > 0: st.progress(min(t_actual / t_budget, 1.0))
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 予算編集
    with st.expander("⚙️ 予算設定"):
        edit = [{"項目": c, "予算": budget.get(c, 0), "実績": actual.get(c, 0)} for c in CATEGORIES]
        res = st.data_editor(pd.DataFrame(edit), use_container_width=True, hide_index=True)
        if st.button("予算保存"):
            for _, r in res.iterrows(): set_category_budget(selected_month, r["項目"], r["予算"])
            st.success("保存完了")
            time.sleep(0.5)
            st.rerun()

    # 詳細リスト
    st.subheader("支出リスト")
    if not df_month.empty:
        # 見やすい表
        st.dataframe(
            df_month.sort_values("date", ascending=False)[["date", "category", "item", "amount"]],
            use_container_width=True, hide_index=True
        )
        # 削除機能
        with st.expander("🗑️ 削除"):
            opts = {f"{r['date']} {r['item']} ¥{r['amount']}": r['id'] for _, r in df_month.sort_values("date", ascending=False).iterrows()}
            dels = st.multiselect("削除する項目", list(opts.keys()))
            if st.button("削除実行"):
                for l in dels: delete_expense(opts[l])
                st.rerun()
