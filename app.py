import calendar
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

DB_PATH = "spending_data.db"
CATEGORY_CONFIG = {
    "food": {"label": "Food", "color": "#2563eb"},
    "shopping": {"label": "Shopping", "color": "#db2777"},
    "leisure": {"label": "Leisure", "color": "#16a34a"},
    "other": {"label": "Other", "color": "#ea580c"},
}

CAR_CATALOG = [
    {"brand": "Toyota", "model": "Corolla", "price": 24000},
    {"brand": "Honda", "model": "Civic", "price": 27000},
    {"brand": "Mazda", "model": "Mazda3", "price": 28000},
    {"brand": "Hyundai", "model": "Elantra", "price": 25000},
    {"brand": "Kia", "model": "K5", "price": 29000},
    {"brand": "Tesla", "model": "Model 3", "price": 39000},
    {"brand": "BMW", "model": "3 Series", "price": 47000},
    {"brand": "Mercedes-Benz", "model": "C-Class", "price": 51000},
    {"brand": "Audi", "model": "A5", "price": 52000},
    {"brand": "Porsche", "model": "Macan", "price": 64000},
    {"brand": "Land Rover", "model": "Defender", "price": 69000},
    {"brand": "Lexus", "model": "RX", "price": 50000},
]

st.set_page_config(page_title="Spending Pattern AI", layout="wide")


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
    df["spend_date"] = pd.to_datetime(df["spend_date"])
    for col in ["food", "shopping", "leisure", "other", "total"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


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
    mapping = {}
    for row in rows:
        mapping[row[0]] = {
            "food": float(row[1] or 0),
            "shopping": float(row[2] or 0),
            "leisure": float(row[3] or 0),
            "other": float(row[4] or 0),
            "total": float(row[5] or 0),
        }
    return mapping


def avg_per_day(df: pd.DataFrame, start_date: pd.Timestamp | None = None) -> float:
    if df.empty:
        return 0.0
    d = df
    if start_date is not None:
        d = d[d["spend_date"] >= start_date]
    if d.empty:
        return 0.0
    days = max(1, d["spend_date"].nunique())
    return float(d["total"].sum() / days)


@dataclass
class ComparisonStats:
    current_total: float
    prev_day_total: float
    prev_week_avg: float
    prev_month_avg: float


def calculate_comparison(df: pd.DataFrame, selected: date) -> ComparisonStats:
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


def annualized_from_today(today_total: float) -> float:
    return today_total * 365


def projected_month_year(df: pd.DataFrame, selected: date) -> tuple[float, float]:
    selected_ts = pd.Timestamp(selected)
    month_df = df[(df["spend_date"].dt.year == selected_ts.year) & (df["spend_date"].dt.month == selected_ts.month)]
    if month_df.empty:
        daily_avg = avg_per_day(df)
    else:
        daily_avg = float(month_df["total"].mean())
    projected_month = daily_avg * 30
    projected_year = daily_avg * 365
    return projected_month, projected_year


def determine_feedback(latest_row: dict, projected_year: float) -> str:
    total = latest_row.get("total", 0.0)
    if total <= 0:
        return "No spending entered for the selected day. Add data to receive targeted feedback."

    category_values = {k: float(latest_row.get(k, 0.0)) for k in CATEGORY_CONFIG.keys()}
    top_cat = max(category_values, key=category_values.get)
    top_value = category_values[top_cat]
    ratio = (top_value / total) if total else 0

    if ratio >= 0.5 or projected_year >= 50000:
        return (
            f"Strong feedback: {CATEGORY_CONFIG[top_cat]['label']} is dominating your daily spend profile. "
            "At this pace, your cash burn is structurally too high. "
            "Freeze non-essential purchases for 7 days and cap this category immediately."
        )

    if ratio >= 0.35 or projected_year >= 30000:
        return (
            f"Warning: {CATEGORY_CONFIG[top_cat]['label']} is above a healthy range. "
            "Apply a fixed daily cap and delay non-urgent purchases by 24 hours."
        )

    return "Your spending mix is currently balanced. Keep tracking and maintain category caps."


def find_car_for_budget(amount: float) -> dict:
    sorted_cars = sorted(CAR_CATALOG, key=lambda x: x["price"])
    affordable = [c for c in sorted_cars if c["price"] <= amount]
    if affordable:
        return affordable[-1]
    return sorted_cars[0]


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
                for cat in ["food", "shopping", "leisure", "other"]:
                    value = rec.get(cat, 0.0)
                    if value > 0:
                        bars.append(
                            f"<div class='bar' style='background:{CATEGORY_CONFIG[cat]['color']}'>{CATEGORY_CONFIG[cat]['label']} ${value:,.0f}</div>"
                        )
                bars_html = "".join(bars) if bars else ""
                html.append(
                    f"<td><div class='day'>{day_num}</div>{bars_html}<div class='total'>Total ${rec.get('total', 0):,.0f}</div></td>"
                )
            else:
                html.append(f"<td><div class='day'>{day_num}</div></td>")
        html.append("</tr>")

    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def apply_style() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Libre+Baskerville:wght@400;700&display=swap');

        .stApp {
            background:
                radial-gradient(1000px 500px at 0% -20%, #e2e8f0 0%, transparent 60%),
                radial-gradient(1000px 500px at 100% 0%, #f1f5f9 0%, transparent 65%),
                #f8fafc;
            color: #0f172a;
            font-family: 'Manrope', sans-serif;
        }

        h1, h2, h3 {
            font-family: 'Libre Baskerville', serif;
            letter-spacing: -0.02em;
        }

        .hero {
            border: 1px solid #cbd5e1;
            background: rgba(255,255,255,0.88);
            border-radius: 18px;
            padding: 20px;
            margin-bottom: 14px;
        }

        .hero-title {
            font-size: 1.7rem;
            font-weight: 700;
            margin-bottom: 6px;
        }

        .hero-sub {
            color: #334155;
            font-size: 0.95rem;
        }

        .calendar-wrap table {width:100%; border-collapse:collapse; table-layout:fixed;}
        .calendar-wrap th {border:1px solid #cbd5e1; background:#eef2ff; padding:7px; font-size:12px;}
        .calendar-wrap td {border:1px solid #cbd5e1; height:116px; vertical-align:top; padding:6px; background:#ffffffd6;}
        .day {font-weight:700; font-size:12px; margin-bottom:5px;}
        .bar {padding:2px 6px; border-radius:999px; color:#fff; font-size:10px; margin-bottom:4px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis;}
        .total {font-size:11px; color:#0f172a; margin-top:4px; font-weight:600;}

        .legend {
            display:flex; gap:8px; flex-wrap:wrap; margin:8px 0 14px 0;
        }
        .legend-item {
            padding:4px 8px; border-radius:999px; color:#fff; font-size:12px; font-weight:600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


init_db()
apply_style()

st.markdown(
    """
    <div class='hero'>
      <div class='hero-title'>Spending Pattern AI</div>
      <div class='hero-sub'>Track daily expenses, detect risk patterns, and receive clear savings direction.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

selected_date = st.date_input("Date", value=date.today(), max_value=date.today())
selected_iso = selected_date.isoformat()
existing = get_spending_by_date(selected_iso) or {"food": 0.0, "shopping": 0.0, "leisure": 0.0, "other": 0.0, "total": 0.0}

form_col, summary_col = st.columns([1.1, 1], gap="large")

with form_col:
    st.subheader("Daily Inputs")
    food = st.number_input("Food", min_value=0.0, step=1.0, value=float(existing.get("food", 0.0)))
    shopping = st.number_input("Shopping", min_value=0.0, step=1.0, value=float(existing.get("shopping", 0.0)))
    leisure = st.number_input("Leisure", min_value=0.0, step=1.0, value=float(existing.get("leisure", 0.0)))
    other = st.number_input("Other", min_value=0.0, step=1.0, value=float(existing.get("other", 0.0)))

    live_total = food + shopping + leisure + other
    st.metric("Daily Total", f"${live_total:,.0f}")

    if st.button("Save Expense", type="primary"):
        upsert_spending(selected_iso, float(food), float(shopping), float(leisure), float(other))
        st.success(f"Saved for {selected_iso}")

with summary_col:
    st.subheader("Annualized Perspective")
    annual_if_repeat = annualized_from_today(live_total)
    st.metric("If Today Repeats For 1 Year", f"${annual_if_repeat:,.0f}")

    car = find_car_for_budget(annual_if_repeat)
    st.write("Reference car at this annualized spend:")
    st.write(f"Brand: {car['brand']}")
    st.write(f"Model: {car['model']}")
    st.write(f"Price: ${car['price']:,.0f}")

all_df = load_all_data()
comparison = calculate_comparison(all_df, selected_date)
projected_month, projected_year = projected_month_year(all_df, selected_date)

st.subheader("Comparisons")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Selected Day", f"${comparison.current_total:,.0f}")
c2.metric("Previous Day", f"${comparison.prev_day_total:,.0f}")
c3.metric("Prev 7-Day Avg", f"${comparison.prev_week_avg:,.0f}")
c4.metric("Prev 30-Day Avg", f"${comparison.prev_month_avg:,.0f}")

p1, p2 = st.columns(2)
p1.metric("Projected Monthly Spend", f"${projected_month:,.0f}")
p2.metric("Projected Yearly Spend", f"${projected_year:,.0f}")

latest_row = {"food": food, "shopping": shopping, "leisure": leisure, "other": other, "total": live_total}
feedback = determine_feedback(latest_row, projected_year)
st.subheader("Feedback")
st.write(feedback)

st.subheader("Category Trends")
if not all_df.empty:
    trend_df = all_df.copy().sort_values("spend_date")
    trend_df = trend_df.set_index("spend_date")[["food", "shopping", "leisure", "other", "total"]]
    st.area_chart(trend_df[["food", "shopping", "leisure", "other"]])
    st.line_chart(trend_df[["total"]])
else:
    st.info("No saved records yet.")

st.subheader("Monthly Calendar")
mcol1, mcol2 = st.columns(2)
with mcol1:
    year = st.selectbox("Year", options=list(range(date.today().year - 2, date.today().year + 2)), index=2)
with mcol2:
    month = st.selectbox("Month", options=list(range(1, 13)), index=date.today().month - 1)

legend_html = ["<div class='legend'>"]
for key, cfg in CATEGORY_CONFIG.items():
    legend_html.append(f"<span class='legend-item' style='background:{cfg['color']}'>{cfg['label']}</span>")
legend_html.append("</div>")
st.markdown("".join(legend_html), unsafe_allow_html=True)

month_map = get_month_map(year, month)
render_calendar(year, month, month_map)

with st.expander("Run"):
    st.code("pip install -r requirements.txt\nstreamlit run app.py", language="bash")
