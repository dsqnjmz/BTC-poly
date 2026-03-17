import streamlit as st
import requests
import json
import re
import time
import pandas as pd
import concurrent.futures  # 🚀 引入 Python 的多线程并发库
from datetime import datetime, timedelta

# 配置网页标题和宽屏模式
st.set_page_config(page_title="BTC 概率曲面雷达 (极速版)", layout="wide")

@st.cache_data(ttl=60)
def fetch_data(max_days=9):
    today = datetime.now()
    price_pattern = re.compile(r"\$?(\d{2,3}(?:,\d{3})*)")
    gamma_url = "https://gamma-api.polymarket.com/events"
    
    # ================= 阶段 1：快速收集所有“钥匙” =================
    tasks = [] # 存放所有需要去查价格的任务
    
    for i in range(max_days):
        target_date = today + timedelta(days=i)
        month_str = target_date.strftime("%B").lower()
        day_int = target_date.day
        predicted_slug = f"bitcoin-above-on-{month_str}-{day_int}"
        
        display_date = f"{target_date.month}月{target_date.day}日"
        
        try:
            # 获取当天的 Event 只需要请求 1 次，非常快
            res = requests.get(gamma_url, params={"slug": predicted_slug}, timeout=5)
            events = res.json()
        except:
            continue
            
        if not events:
            continue
            
        event = events[0]
        for market in event.get("markets", []):
            question = market.get("question", "")
            token_ids = market.get("clobTokenIds", "[]")
            
            if isinstance(token_ids, str):
                try: token_ids = json.loads(token_ids)
                except: token_ids = []
                
            match = price_pattern.search(question)
            if match and len(token_ids) > 0:
                strike = int(match.group(1).replace(",", ""))
                # 我们不再这里慢慢排队查价格，而是把任务装进列表里
                tasks.append({
                    "日期": display_date,
                    "真实时间": target_date,
                    "strike": strike,
                    "yes_token": token_ids[0]
                })

    # ================= 阶段 2：火力全开！多线程并发查盘口 =================
    # 定义单次查价的独立函数
    def fetch_midpoint(task):
        clob_url = f"https://clob.polymarket.com/midpoint?token_id={task['yes_token']}"
        try:
            clob_res = requests.get(clob_url, timeout=5)
            mid_price = float(clob_res.json().get("mid", 0)) if clob_res.status_code == 200 else 0.0
        except:
            mid_price = 0.0
        task['prob_above'] = mid_price
        return task

    # 🚀 瞬间开启 15 个并发线程（工人），把那近 100 个查价任务一瞬间做完！
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        completed_tasks = list(executor.map(fetch_midpoint, tasks))

    # ================= 阶段 3：数据重组与区间计算 =================
    # 把打乱的并发结果重新按照日期分组整理
    grouped_markets = {}
    for t in completed_tasks:
        d = t["日期"]
        if d not in grouped_markets:
            grouped_markets[d] = {"真实时间": t["真实时间"], "markets": []}
        grouped_markets[d]["markets"].append(t)

    all_data = []
    
    # 按天计算区间概率
    for d, info in grouped_markets.items():
        markets = info["markets"]
        markets.sort(key=lambda x: x["strike"]) # 把当天的价格从低到高排好
        
        for j in range(len(markets)):
            current_strike = markets[j]["strike"]
            current_prob = markets[j]["prob_above"]
            
            if j < len(markets) - 1:
                next_strike = markets[j+1]["strike"]
                next_prob = markets[j+1]["prob_above"]
                interval_prob = max(0.0, current_prob - next_prob) * 100
                range_str = f"{current_strike//1000}k - {next_strike//1000}k" 
            else:
                interval_prob = current_prob * 100
                range_str = f"> {current_strike//1000}k"
                
            all_data.append({
                "日期": d,
                "价格区间": range_str,
                "预测概率 (%)": round(interval_prob, 2),
                "排序用价格": current_strike, 
                "真实时间": info["真实时间"]
            })
            
    return pd.DataFrame(all_data)

# ================= 网页 UI 部分 =================

st.title("🎯 BTC 隐含概率曲面热力矩阵 (极速版)")
st.markdown("基于 PolyMarket 真金白银盘口深度，逆向推导的未来多日价格共识矩阵。颜色越红，代表资金押注该区间发生的概率极高。")

with st.spinner('🚀 正在启动多线程引擎，瞬间扫盘中...'):
    df = fetch_data()

if not df.empty:
    st.success(f"数据扫盘完毕！耗时极短。最后更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    df['预测概率 (%)'] = pd.to_numeric(df['预测概率 (%)'], errors='coerce').fillna(0)
    pivot_df = df.pivot_table(index='价格区间', columns='日期', values='预测概率 (%)', aggfunc='mean').fillna(0)
    
    ordered_prices = df.sort_values('排序用价格', ascending=False)['价格区间'].unique().tolist()
    ordered_dates = df.sort_values('真实时间')['日期'].unique().tolist()
    
    pivot_df = pivot_df.reindex(index=ordered_prices, columns=ordered_dates).fillna(0)
    
    st.markdown("### 📊 市场共识概率分布矩阵 (%)")
    
    styled_df = pivot_df.style.background_gradient(cmap='YlOrRd', axis=None).format("{:.1f}")
    st.dataframe(styled_df, use_container_width=True, height=500)

else:
    st.error("未能抓取到有效数据，请检查网络或确认官方今天是否有对应盘口。")

st.info("⏳ 监控雷达运转中... 本页面每 10 分钟全自动极速扫盘一次。")
time.sleep(600) 
st.rerun()