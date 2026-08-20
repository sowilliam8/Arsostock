import streamlit as st
import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, date
from typing import Dict, List

# ==================== 設定 ====================
DATA_FILE = "portfolio_data.json"
st.set_page_config(
    page_title="月供股票投資組合追蹤",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 工具函數 ====================
def normalize_ticker(code: str) -> str:
    code = str(code).strip().upper().replace(" ", "")
    if code.endswith(".HK"):
        num = code[:-3].lstrip("0") or "0"
        return f"{int(num):04d}.HK"
    if code.isdigit():
        return f"{int(code):04d}.HK"
    return code


def load_data() -> Dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"holdings": {}, "sells": []}


def save_data(data: Dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_stock_info(ticker: str) -> Dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info
        
        current = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        prev_close = info.get("previousClose") or current
        volume = info.get("volume") or info.get("regularMarketVolume") or 0
        name = info.get("longName") or info.get("shortName") or ticker
        pe = info.get("trailingPE")
        div_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
        
        if div_yield is not None and div_yield < 1:
            div_yield = div_yield * 100
            
        return {
            "success": True,
            "name": name,
            "current": float(current) if current else None,
            "prev_close": float(prev_close) if prev_close else None,
            "volume": int(volume) if volume else 0,
            "pe": float(pe) if pe else None,
            "div_yield": float(div_yield) if div_yield else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def calc_realized_by_year(sells: List[Dict], ticker: str, avg_cost: float) -> Dict[int, float]:
    """計算指定股票各年份的實現盈虧"""
    result = {y: 0.0 for y in range(2023, 2029)}
    for s in sells:
        if s.get("ticker") != ticker:
            continue
        try:
            sell_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
            year = sell_date.year
            if 2023 <= year <= 2028:
                result[year] += (float(s["price"]) - avg_cost) * float(s["qty"])
        except:
            continue
    return result


# ==================== 主介面 ====================
st.title("📈 月供股票投資組合追蹤")
st.caption("支援港股 · 自動計算多年度實現盈虧（2023–2028）")

data = load_data()
holdings: Dict = data.get("holdings", {})
sells: List = data.get("sells", [])

# ---------- 側邊欄 ----------
with st.sidebar:
    st.header("➕ 新增 / 更新持倉")
    
    with st.form("add_holding", clear_on_submit=True):
        code_input = st.text_input("股票代號", placeholder="700 / 0700 / 0700.HK")
        avg_price = st.number_input("平均買入價 (HK$)", min_value=0.0, step=0.01, format="%.3f")
        qty = st.number_input("持貨數量 (股)", min_value=0, step=100)
        
        if st.form_submit_button("新增 / 更新持倉", type="primary", use_container_width=True):
            if code_input and avg_price > 0 and qty > 0:
                ticker = normalize_ticker(code_input)
                info = get_stock_info(ticker)
                if info["success"]:
                    holdings[ticker] = {
                        "avg_cost": float(avg_price),
                        "qty": int(qty),
                        "name": info["name"]
                    }
                    data["holdings"] = holdings
                    save_data(data)
                    st.success(f"已更新：{info['name']}")
                    st.rerun()
                else:
                    st.error("無法取得股票資料，請檢查代號")
    
    st.divider()
    st.header("📉 記錄賣出")
    
    if holdings:
        with st.form("add_sell"):
            sell_ticker = st.selectbox(
                "選擇股票",
                options=list(holdings.keys()),
                format_func=lambda x: f"{holdings[x]['name']} ({x})"
            )
            sell_date = st.date_input("賣出日期", value=date.today())
            sell_qty = st.number_input("賣出股數", min_value=1, step=100)
            sell_price = st.number_input("賣出價 (HK$)", min_value=0.0, step=0.01, format="%.3f")
            
            if st.form_submit_button("確認賣出", use_container_width=True):
                current_qty = holdings[sell_ticker]["qty"]
                if sell_qty > current_qty:
                    st.error(f"持貨不足（目前 {current_qty} 股）")
                else:
                    avg_cost = holdings[sell_ticker]["avg_cost"]
                    holdings[sell_ticker]["qty"] -= sell_qty
                    if holdings[sell_ticker]["qty"] <= 0:
                        del holdings[sell_ticker]
                    
                    sells.append({
                        "ticker": sell_ticker,
                        "date": sell_date.strftime("%Y-%m-%d"),
                        "qty": int(sell_qty),
                        "price": float(sell_price),
                        "avg_cost": avg_cost
                    })
                    data["holdings"] = holdings
                    data["sells"] = sells
                    save_data(data)
                    st.success("賣出已記錄")
                    st.rerun()
    else:
        st.info("請先新增持倉")

# ---------- 主畫面 ----------
if not holdings:
    st.info("👈 請先在左側新增持倉")
    st.stop()

# 抓取資料並計算
rows = []
total_mv = 0.0
total_cost = 0.0
total_unrealized = 0.0
total_div = 0.0

progress = st.progress(0, text="更新股價中...")

for i, (ticker, h) in enumerate(holdings.items()):
    info = get_stock_info(ticker)
    progress.progress((i + 1) / len(holdings), text=f"更新：{ticker}")
    
    if not info["success"] or info["current"] is None:
        continue
    
    current = info["current"]
    prev = info["prev_close"] or current
    avg = h["avg_cost"]
    qty = h["qty"]
    
    mv = current * qty
    cost = avg * qty
    unrealized = mv - cost
    unrealized_pct = (unrealized / cost * 100) if cost else 0
    daily_change = current - prev
    daily_pnl = daily_change * qty
    daily_pct = (daily_change / prev * 100) if prev else 0
    pe = info["pe"]
    div_yield = info["div_yield"] or 0
    annual_div = mv * (div_yield / 100)
    
    # 各年份實現盈虧
    year_profits = calc_realized_by_year(sells, ticker, avg)
    
    total_mv += mv
    total_cost += cost
    total_unrealized += unrealized
    total_div += annual_div
    
    rows.append({
        "股票代號": ticker,
        "公司名": info["name"],
        "現價": current,
        "升跌%": daily_pct,
        "即日升跌": daily_change,
        "即日賺蝕": daily_pnl,
        "平均買入價": avg,
        "持貨數量": qty,
        "盈利/虧損 (每股)": current - avg,
        "賺蝕價": unrealized,
        "賺蝕百分比": unrealized_pct,
        "整體持有成份比例": 0,  # 稍後計算
        "成交量": info["volume"],
        "現時價值": mv,
        "上年息率LFY": div_yield,
        "年利息參考": annual_div,
        "滾動市盈率": pe,
        "獲利2023年": year_profits[2023],
        "獲利2024年": year_profits[2024],
        "獲利2025年": year_profits[2025],
        "獲利2026年": year_profits[2026],
        "獲利2027年": year_profits[2027],
        "獲利2028年": year_profits[2028],
    })

progress.empty()

# 計算持有比例
for r in rows:
    r["整體持有成份比例"] = (r["現時價值"] / total_mv * 100) if total_mv else 0

# ---------- 總覽 ----------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("組合總市值", f"HK$ {total_mv:,.0f}")
c2.metric("總未實現盈虧", f"HK$ {total_unrealized:,.0f}",
          f"{(total_unrealized/total_cost*100):+.2f}%" if total_cost else None)
c3.metric("預計全年股息", f"HK$ {total_div:,.0f}")
c4.metric("持倉數量", f"{len(rows)} 隻")
c5.metric("資料更新時間", datetime.now().strftime("%H:%M:%S"))

st.divider()

# ---------- 詳細表格 ----------
df = pd.DataFrame(rows)

# 欄位順序完全依照你的要求
column_order = [
    "股票代號", "公司名", "現價", "升跌%", "即日升跌", "即日賺蝕",
    "平均買入價", "持貨數量", "盈利/虧損 (每股)", "賺蝕價", "賺蝕百分比",
    "整體持有成份比例", "成交量", "現時價值",
    "上年息率LFY", "年利息參考", "滾動市盈率",
    "獲利2023年", "獲利2024年", "獲利2025年", "獲利2026年", "獲利2027年", "獲利2028年"
]
df = df[column_order]

st.subheader("持倉明細")
st.dataframe(
    df.style.format({
        "現價": "{:.3f}",
        "升跌%": "{:+.2f}%",
        "即日升跌": "{:+.3f}",
        "即日賺蝕": "{:+,.0f}",
        "平均買入價": "{:.3f}",
        "盈利/虧損 (每股)": "{:+.3f}",
        "賺蝕價": "{:+,.0f}",
        "賺蝕百分比": "{:+.2f}%",
        "整體持有成份比例": "{:.1f}%",
        "成交量": "{:,.0f}",
        "現時價值": "{:,.0f}",
        "上年息率LFY": "{:.2f}%",
        "年利息參考": "{:,.0f}",
        "滾動市盈率": "{:.1f}",
        "獲利2023年": "{:+,.0f}",
        "獲利2024年": "{:+,.0f}",
        "獲利2025年": "{:+,.0f}",
        "獲利2026年": "{:+,.0f}",
        "獲利2027年": "{:+,.0f}",
        "獲利2028年": "{:+,.0f}",
    }),
    use_container_width=True,
    height=520
)

# ---------- 賣出紀錄 ----------
with st.expander("📜 查看所有賣出紀錄"):
    if sells:
        st.dataframe(pd.DataFrame(sells), use_container_width=True)
        if st.button("清除所有賣出紀錄"):
            data["sells"] = []
            save_data(data)
            st.rerun()
    else:
        st.info("目前沒有賣出紀錄")

st.divider()
col_a, col_b = st.columns(2)
with col_a:
    if st.button("🔄 立即重新整理", use_container_width=True):
        st.rerun()
with col_b:
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 匯出 CSV", csv, "portfolio.csv", "text/csv", use_container_width=True)

st.caption("資料來源：Yahoo Finance（約 15 分鐘延遲）· 僅供個人參考")
