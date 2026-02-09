import calendar
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

DB_PATH = "spending_data.db"
CATEGORY_ORDER = ["food", "shopping", "leisure", "other"]
CATEGORY_CONFIG = {
    "food": {"label": "Food/Beverage", "color": "#d1d5db"},
    "shopping": {"label": "Shopping", "color": "#e5e7eb"},
    "leisure": {"label": "Hobbies", "color": "#cbd5e1"},
    "other": {"label": "Etc (Travel)", "color": "#f1f5f9"},
}

CAR_CATALOG = [
    {"brand": "Toyota", "model": "Corolla", "price": 24000},
    {"brand": "Honda", "model": "Civic", "price": 27000},
    {"brand": "Mazda", "model": "Mazda3", "price": 28000},
    {"brand": "Hyundai", "model": "Elantra", "price": 25000},
    {"brand": "Tesla", "model": "Model 3", "price": 39000},
    {"brand": "BMW", "model": "3 Series", "price": 47000},
    {"brand": "Mercedes-Benz", "model": "C-Class", "price": 51000},
]

MACBOOK_CATALOG = [
    {"brand": "Apple", "model": "MacBook Air 13 (M2)", "price": 999},
    {"brand": "Apple", "model": "MacBook Air 15 (M3)", "price": 1299},
    {"brand": "Apple", "model": "MacBook Pro 14 (M3)", "price": 1599},
    {"brand": "Apple", "model": "MacBook Pro 14 (M4 Pro)", "price": 1999},
    {"brand": "Apple", "model": "MacBook Pro 16 (M4 Pro)", "price": 2499},
]

IPHONE_CATALOG = [
    {"brand": "Apple", "model": "iPhone SE", "price": 429},
    {"brand": "Apple", "model": "iPhone 15", "price": 799},
    {"brand": "Apple", "model": "iPhone 15 Plus", "price": 899},
    {"brand": "Apple", "model": "iPhone 16", "price": 899},
    {"brand": "Apple", "model": "iPhone 16 Pro", "price": 1099},
    {"brand": "Apple", "model": "iPhone 16 Pro Max", "price": 1199},
]

st.set_page_config(page_title="Money Tracker AI", layout="wide")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_spending (
            spend_date TEXT PRIMARY KEY,
            food REAL DEFAULT 0,
            shopping REAL DEFAULT 0,
            leisure REAL DEFAULT 0,
            other REAL DEFAULT 0,
            total REAL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def upsert_spending(spend_date: str, food: float, shopping: float, leisure: float, other: float) -> None:
    total = food + shopping + leisure + other
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO daily_spending (spend_date, food, shopping, leisure, other, total, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(spend_date) DO UPDATE SET
            food=excluded.food,
            shopping=excluded.shopping,
            leisure=excluded.leisure,
            other=excluded.other,
            total=excluded.total,
            updated_at=excluded.updated_at
        """,
        (spend_date, food, shopping, leisure, other, total, now, now),
    )
    conn.commit()
    conn.close()


def get_spending_by_date(spend_date: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT spend_date, food, shopping, leisure, other, total
        FROM daily_spending
        WHERE spend_date = ?
        """,
        (spend_date,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "spend_date": row[0],
        "food": float(row[1] or 0),
        "shopping": float(row[2] or 0),
        "leisure": float(row[3] or 0),
        "other": float(row[4] or 0),
        "total": float(row[5] or 0),
    }


def load_all_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT spend_date, food, shopping, leisure, other, total FROM daily_spending ORDER BY spend_date ASC",
        conn,
    )
    conn.close()
    if df.empty:
        return df
    df["spend_date"] = pd.to_datetime(df["spend_date"], errors="coerce")
    df = df.dropna(subset=["spend_date"]).copy()
    for col in ["food", "shopping", "leisure", "other", "total"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def ensure_datetime_spend_date(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["spend_date"] = pd.to_datetime(out["spend_date"], errors="coerce")
    out = out.dropna(subset=["spend_date"])
    return out


def get_month_map(year: int, month: int) -> dict:
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-31"
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT spend_date, food, shopping, leisure, other, total
        FROM daily_spending
        WHERE spend_date BETWEEN ? AND ?
        ORDER BY spend_date ASC
        """,
        (start, end),
    )
    rows = cur.fetchall()
    conn.close()
    month_data = {}
    for row in rows:
        month_data[row[0]] = {
            "food": float(row[1] or 0),
            "shopping": float(row[2] or 0),
            "leisure": float(row[3] or 0),
            "other": float(row[4] or 0),
            "total": float(row[5] or 0),
        }
    return month_data


@dataclass
class ComparisonStats:
    current_total: float
    prev_day_total: float
    prev_week_avg: float
    prev_month_avg: float


def calculate_comparison(df: pd.DataFrame, selected: date) -> ComparisonStats:
    df = ensure_datetime_spend_date(df)
    if df.empty:
        return ComparisonStats(0.0, 0.0, 0.0, 0.0)

    selected_ts = pd.Timestamp(selected)
    row = df[df["spend_date"] == selected_ts]
    current_total = float(row["total"].iloc[0]) if not row.empty else 0.0

    prev_day = selected_ts - pd.Timedelta(days=1)
    prev_day_row = df[df["spend_date"] == prev_day]
    prev_day_total = float(prev_day_row["total"].iloc[0]) if not prev_day_row.empty else 0.0

    week_start = selected_ts - pd.Timedelta(days=7)
    week_df = df[(df["spend_date"] >= week_start) & (df["spend_date"] < selected_ts)]
    prev_week_avg = float(week_df["total"].mean()) if not week_df.empty else 0.0

    month_start = selected_ts - pd.Timedelta(days=30)
    month_df = df[(df["spend_date"] >= month_start) & (df["spend_date"] < selected_ts)]
    prev_month_avg = float(month_df["total"].mean()) if not month_df.empty else 0.0

    return ComparisonStats(current_total, prev_day_total, prev_week_avg, prev_month_avg)


def projected_month_year(df: pd.DataFrame, selected: date) -> tuple[float, float]:
    df = ensure_datetime_spend_date(df)
    if df.empty:
        return 0.0, 0.0
    selected_ts = pd.Timestamp(selected)
    month_df = df[(df["spend_date"].dt.year == selected_ts.year) & (df["spend_date"].dt.month == selected_ts.month)]
    daily_avg = float(month_df["total"].mean()) if not month_df.empty else 0.0
    return daily_avg * 30, daily_avg * 365


def annualized_from_today(today_total: float) -> float:
    return today_total * 365


def dominant_category(latest_row: dict) -> tuple[str, float]:
    total = float(latest_row.get("total", 0.0))
    if total <= 0:
        return "food", 0.0
    category_values = {k: float(latest_row.get(k, 0.0)) for k in CATEGORY_ORDER}
    top_cat = max(category_values, key=category_values.get)
    ratio = category_values[top_cat] / total if total else 0.0
    return top_cat, ratio


def determine_feedback(latest_row: dict, projected_year: float) -> str:
    total = float(latest_row.get("total", 0.0))
    if total <= 0:
        return "No spending entered for the selected day. Add values to get actionable feedback."

    top_cat, ratio = dominant_category(latest_row)
    label = CATEGORY_CONFIG[top_cat]["label"]

    if ratio >= 0.5 or projected_year >= 50000:
        return (
            f"Strong feedback: {label} is taking too much of your daily budget. "
            "Your current pace is not sustainable. Set a strict hard cap immediately and pause non-essential spending for the next 7 days."
        )
    if ratio >= 0.35 or projected_year >= 30000:
        return (
            f"Warning: {label} is above your healthy spending range. "
            "Apply a daily cap and enforce a 24-hour delay rule before any optional purchase."
        )
    return "Your spending distribution is stable. Keep consistent daily caps and continue tracking."


def pick_best_item(catalog: list[dict], budget: float) -> dict:
    sorted_items = sorted(catalog, key=lambda x: x["price"])
    affordable = [item for item in sorted_items if item["price"] <= budget]
    if affordable:
        return affordable[-1]
    return sorted_items[0]


def get_rich_quote(openai_api_key: str, model_name: str, today_total: float, projected_year: float, feedback: str):
    if not openai_api_key:
        return None, "Enter OpenAI API key to generate a rich-mindset quote."
    try:
        from openai import OpenAI

        prompt = f"""
Create one strong money-discipline quote in English.
Context:
- Today's spend: ${today_total:,.2f}
- Projected yearly spend: ${projected_year:,.2f}
- Feedback: {feedback}

Rules:
- Max 24 words
- No emojis
- Tone: direct, disciplined, premium
- Output one line only
""".strip()

        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You write concise high-impact money quotes."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        text = (response.choices[0].message.content or "").strip().replace("\n", " ")
        return text, None
    except Exception as e:
        return None, f"OpenAI request failed: {e}"


def product_image_url(brand: str, model: str, product_type: str) -> str:
    safe_model = model.replace(" ", "+")
    if product_type == "car":
        return f"https://dummyimage.com/300x180/ffffff/111111.png&text={brand}+{safe_model}"
    if product_type == "macbook":
        return f"https://dummyimage.com/300x180/ffffff/111111.png&text={safe_model}"
    if product_type == "iphone":
        return f"https://dummyimage.com/300x180/ffffff/111111.png&text={safe_model}"
    return "https://dummyimage.com/300x180/ffffff/111111.png&text=Product"


def render_calendar(year: int, month: int, month_map: dict) -> None:
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(year, month)
    weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    html = ["<div class='calendar-wrap'><table><thead><tr>"]
    for wd in weekdays:
        html.append(f"<th>{wd}</th>")
    html.append("</tr></thead><tbody>")

    for week in weeks:
        html.append("<tr>")
        for day_num in week:
            if day_num == 0:
                html.append("<td></td>")
                continue
            key = f"{year:04d}-{month:02d}-{day_num:02d}"
            rec = month_map.get(key)
            if rec:
                bars = []
                for cat in CATEGORY_ORDER:
                    value = rec.get(cat, 0.0)
                    if value > 0:
                        bars.append(
                            f"<div class='bar' style='border-color:{CATEGORY_CONFIG[cat]['color']}'>{CATEGORY_CONFIG[cat]['label']}: ${value:,.0f}</div>"
                        )
                bars_html = "".join(bars)
                html.append(
                    f"<td><div class='day'>{day_num}</div>{bars_html}<div class='total'>Total: ${rec.get('total', 0):,.0f}</div></td>"
                )
            else:
                html.append(f"<td><div class='day'>{day_num}</div></td>")
        html.append("</tr>")
    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def category_timeseries_chart(df: pd.DataFrame) -> alt.Chart:
    if df.empty:
        return alt.Chart(pd.DataFrame({"spend_date": [], "category": [], "amount": []}))

    long_df = df[["spend_date", "food", "shopping", "leisure", "other"]].melt(
        id_vars=["spend_date"],
        var_name="category",
        value_name="amount",
    )
    long_df["category"] = long_df["category"].map(lambda x: CATEGORY_CONFIG[x]["label"])

    return (
        alt.Chart(long_df)
        .mark_line(strokeWidth=2, color="#9ca3af", strokeDash=[6, 4])
        .encode(
            x=alt.X("spend_date:T", title="Date"),
            y=alt.Y("amount:Q", title="Amount ($)"),
            strokeDash=alt.StrokeDash("category:N", title="Category"),
            detail="category:N",
            tooltip=["spend_date:T", "category:N", alt.Tooltip("amount:Q", format=",.2f")],
        )
        .properties(height=320)
        .configure_view(fill="#ffffff", stroke="#e5e7eb")
    )


def apply_style() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: #ffffff;
            color: #111111;
            font-family: Georgia, "Times New Roman", serif;
        }
        html, body, [class*="css"] {
            font-family: Georgia, "Times New Roman", serif;
            color: #111111;
        }
        p, span, label, div, input, textarea {
            color: #111111 !important;
        }
        [data-testid="stMetricLabel"] p,
        [data-testid="stMetricValue"] div,
        [data-testid="stMetricDelta"] div {
            color: #111111 !important;
        }
        [data-testid="stMarkdownContainer"] * {
            color: #111111 !important;
        }
        .stNumberInput input, .stDateInput input, .stTextInput input {
            color: #111111 !important;
            background: transparent !important;
            border: 1px solid #d1d5db !important;
        }
        .stSelectbox div[data-baseweb="select"] > div {
            background: transparent !important;
            border: 1px solid #d1d5db !important;
        }
        .stButton > button,
        .stDownloadButton > button {
            color: #111111 !important;
            background: #f3f4f6 !important;
            border: 1px solid #d1d5db !important;
            border-radius: 4px !important;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover {
            background: #e5e7eb !important;
            border-color: #d1d5db !important;
        }
        .stButton > button[kind="primary"] {
            background: #e5e7eb !important;
            color: #111111 !important;
            border: 1px solid #d1d5db !important;
        }
        .hero {
            border: 1px solid #e5e7eb;
            background: #ffffff;
            padding: 20px;
            margin-bottom: 16px;
            text-align: center;
        }
        .hero-title {
            font-size: 2.0rem;
            font-weight: 700;
            margin-bottom: 6px;
            letter-spacing: 0.02em;
        }
        .hero-sub {
            font-size: 0.95rem;
            color: #222222;
        }
        .calendar-wrap table {width:100%; border-collapse:collapse; table-layout:fixed;}
        .calendar-wrap th {border:1px solid #e5e7eb; background:#fafafa; padding:7px; font-size:12px;}
        .calendar-wrap td {border:1px solid #e5e7eb; height:130px; vertical-align:top; padding:6px; background:#ffffff;}
        .day {font-weight:700; font-size:12px; margin-bottom:5px;}
        .bar {padding:2px 6px; border-radius:3px; color:#111111; font-size:10px; margin-bottom:4px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; border:1px solid #d1d5db; background:transparent !important;}
        .total {font-size:11px; color:#111111; margin-top:4px; font-weight:700;}
        .legend {display:flex; gap:8px; flex-wrap:wrap; margin:8px 0 14px 0;}
        .legend-item {padding:3px 8px; border-radius:3px; color:#111111; font-size:12px; font-weight:600; border:1px solid #d1d5db; background:transparent !important;}
        .image-box {border:1px solid #e5e7eb; padding:6px; background:#ffffff;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    if "rich_quote" not in st.session_state:
        st.session_state.rich_quote = ""


init_db()
init_state()
apply_style()

st.markdown(
    """
    <div class='hero'>
      <div class='hero-title'>MONEY TRACKER AI</div>
      <div class='hero-sub'>Record spending, analyze patterns, project outcomes, and enforce disciplined budgeting.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("AI Settings")
    openai_api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
    model_name = st.text_input("Model", value=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

selected_date = st.date_input("Date", value=date.today(), max_value=date.today())
selected_iso = selected_date.isoformat()
existing = get_spending_by_date(selected_iso) or {"food": 0.0, "shopping": 0.0, "leisure": 0.0, "other": 0.0}

left, right = st.columns([1.15, 1], gap="large")

with left:
    st.subheader("Daily Inputs")
    food = st.number_input("Food/Beverage ($)", min_value=0.0, step=1.0, format="%.2f", value=float(existing.get("food", 0.0)))
    shopping = st.number_input("Shopping ($)", min_value=0.0, step=1.0, format="%.2f", value=float(existing.get("shopping", 0.0)))
    hobbies = st.number_input("Hobbies ($)", min_value=0.0, step=1.0, format="%.2f", value=float(existing.get("leisure", 0.0)))
    other = st.number_input("Etc (Travel) ($)", min_value=0.0, step=1.0, format="%.2f", value=float(existing.get("other", 0.0)))

    live_total = float(food + shopping + hobbies + other)
    st.metric("Daily Total", f"${live_total:,.2f}")

    if st.button("Save Expense", type="primary"):
        upsert_spending(selected_iso, float(food), float(shopping), float(hobbies), float(other))
        st.success(f"Saved spending data for {selected_iso}.")

with right:
    st.subheader("Annualized Perspective")
    annual_if_repeat = annualized_from_today(live_total)
    car = pick_best_item(CAR_CATALOG, annual_if_repeat)

    annual_text, annual_img = st.columns([1.7, 1], gap="small")
    with annual_text:
        st.write("If this daily spending continues (365 days):")
        st.write(f"Consumed Amount: ${annual_if_repeat:,.2f}")
        st.write(f"Brand: {car['brand']}")
        st.write(f"Model: {car['model']}")
        st.write(f"Model Price: ${car['price']:,.2f}")
    with annual_img:
        st.markdown("<div class='image-box'>", unsafe_allow_html=True)
        st.image(product_image_url(car["brand"], car["model"], "car"), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    monthly_if_repeat = live_total * 30
    macbook = pick_best_item(MACBOOK_CATALOG, monthly_if_repeat)
    iphone = pick_best_item(IPHONE_CATALOG, monthly_if_repeat)

    st.subheader("Monthly Perspective")
    monthly_text, monthly_img = st.columns([1.7, 1], gap="small")
    with monthly_text:
        st.write("If this daily spending continues (30 days):")
        st.write(f"Consumed Amount: ${monthly_if_repeat:,.2f}")
        st.write(f"Brand: {macbook['brand']}")
        st.write(f"Model: {macbook['model']}")
        st.write(f"Model Price: ${macbook['price']:,.2f}")
        st.write("---")
        st.write(f"Brand: {iphone['brand']}")
        st.write(f"Model: {iphone['model']}")
        st.write(f"Model Price: ${iphone['price']:,.2f}")
    with monthly_img:
        st.markdown("<div class='image-box'>", unsafe_allow_html=True)
        st.image(product_image_url(macbook["brand"], macbook["model"], "macbook"), use_container_width=True)
        st.image(product_image_url(iphone["brand"], iphone["model"], "iphone"), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

all_df = load_all_data()
comparison = calculate_comparison(all_df, selected_date)
projected_month, projected_year = projected_month_year(all_df, selected_date)

st.subheader("Comparative Insights")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Selected Day", f"${comparison.current_total:,.2f}")
c2.metric("Previous Day", f"${comparison.prev_day_total:,.2f}")
c3.metric("Previous 7-Day Average", f"${comparison.prev_week_avg:,.2f}")
c4.metric("Previous 30-Day Average", f"${comparison.prev_month_avg:,.2f}")

p1, p2 = st.columns(2)
p1.metric("Projected Monthly Spend", f"${projected_month:,.2f}")
p2.metric("Projected Yearly Spend", f"${projected_year:,.2f}")

latest_row = {"food": food, "shopping": shopping, "leisure": hobbies, "other": other, "total": live_total}
feedback = determine_feedback(latest_row, projected_year)

st.subheader("Feedback")
st.write(feedback)

quote_col, btn_col = st.columns([4, 1])
with btn_col:
    generate_quote = st.button("Generate Rich Quote")

if generate_quote:
    quote, err = get_rich_quote(openai_api_key, model_name, live_total, projected_year, feedback)
    if err:
        st.error(err)
    else:
        st.session_state.rich_quote = quote

with quote_col:
    if st.session_state.rich_quote:
        st.write(st.session_state.rich_quote)
    else:
        st.caption("Generate a rich-mindset quote based on your spending profile.")

st.subheader("Category Trends")
if not all_df.empty:
    trend_df = all_df.sort_values("spend_date").copy()
    chart = category_timeseries_chart(trend_df)
    st.altair_chart(chart, use_container_width=True)

    total_chart = (
        alt.Chart(trend_df)
        .mark_line(color="#9ca3af", strokeWidth=2.5, strokeDash=[6, 4])
        .encode(
            x=alt.X("spend_date:T", title="Date"),
            y=alt.Y("total:Q", title="Total ($)"),
            tooltip=["spend_date:T", alt.Tooltip("total:Q", format=",.2f")],
        )
        .properties(height=280)
        .configure_view(fill="#ffffff", stroke="#e5e7eb")
    )
    st.altair_chart(total_chart, use_container_width=True)
else:
    st.info("No saved records yet.")

st.subheader("Monthly Calendar")
y_col, m_col = st.columns(2)
with y_col:
    year = st.selectbox("Year", options=list(range(date.today().year - 2, date.today().year + 2)), index=2)
with m_col:
    month = st.selectbox("Month", options=list(range(1, 13)), index=date.today().month - 1)

legend_html = ["<div class='legend'>"]
for cat in CATEGORY_ORDER:
    cfg = CATEGORY_CONFIG[cat]
    legend_html.append(f"<span class='legend-item' style='border-color:{cfg['color']}'>{cfg['label']}</span>")
legend_html.append("</div>")
st.markdown("".join(legend_html), unsafe_allow_html=True)

month_map = get_month_map(year, month)
render_calendar(year, month, month_map)

with st.expander("Run"):
    st.code("pip install -r requirements.txt\nstreamlit run app.py", language="bash")
