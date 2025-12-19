import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import os

# 환율 데이터 수집 (CSV에서 읽기 - 절대 경로 적용)
@st.cache_data(ttl=3600)
def get_exchange_data_from_csv(start_date, end_date):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    csv_path = os.path.join(root_dir, "data", "exchange_rates.csv")
    
    if not os.path.exists(csv_path):
        st.error(f"❌ 데이터 파일을 찾을 수 없습니다.\n경로: {csv_path}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(csv_path)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        mask = (df.index >= pd.to_datetime(start_date)) & (df.index <= pd.to_datetime(end_date))
        filtered_df = df.loc[mask]
        return filtered_df
    except Exception as e:
        st.error(f"환율 데이터 읽기 오류: {e}")
        return pd.DataFrame()

# 주식 데이터 수집
@st.cache_data(ttl=3600)
def get_stock_data(tickers, start_date, end_date):
    try:
        df = yf.download(tickers, start=start_date, end=end_date, progress=False, auto_adjust=False)
        
        if df.empty: return pd.DataFrame()

        if 'Adj Close' in df.columns: df = df['Adj Close']
        elif 'Close' in df.columns: df = df['Close']
        else:
            try: df = df.xs('Adj Close', axis=1, level=0)
            except KeyError: df = df.xs('Close', axis=1, level=0)

        if isinstance(df, pd.Series): df = df.to_frame(name=tickers[0])
        return df
    except Exception as e:
        st.error(f"주가 데이터 수집 에러: {e}")
        return pd.DataFrame()

def get_merged_market_data(tickers, start, end): 
    df_stock = get_stock_data(tickers, start, end)
    df_exchange = get_exchange_data_from_csv(start, end) 
    
    if df_stock.empty:
        st.warning("주식 데이터를 불러오지 못했습니다.")
        return None
        
    if df_exchange.empty:
        st.warning(f"해당 기간({start} ~ {end})의 환율 데이터가 없습니다.")
        return None

    merged_df = df_stock.join(df_exchange, how='left')
    merged_df['USD_KRW'] = merged_df['USD_KRW'].ffill().bfill()
    return merged_df

def run_monte_carlo(hist_returns, start_price, days, simulations):
    random_returns = np.random.choice(hist_returns, size=(days, simulations), replace=True)
    cum_returns = np.exp(np.cumsum(random_returns, axis=0))
    price_paths = np.zeros((days + 1, simulations))
    price_paths[0] = start_price
    price_paths[1:] = start_price * cum_returns
    return price_paths

#---------------------------------------UI-------------------------------------------

st.title("🛡️ Portfolio PathFinder")

# [모바일 UX] 사이드바 설정 안내
st.info("👈 **왼쪽 사이드바(`>`)**를 열어 종목과 투자금을 설정하세요!")

with st.sidebar:
    st.header("⚙️ 포트폴리오 설정")
    tickers_input = st.text_input("종목 티커 (쉼표 구분)", value="AAPL, GOOGL, NVDA")
    tickers = [t.strip().upper() for t in tickers_input.split(',')]
    investment = st.number_input("초기 투자금 (원화)", value=10000000, step=1000000)
    period = st.date_input("과거 데이터 기간", value=(pd.to_datetime("2024-01-01"), pd.to_datetime("2024-12-01")))
    forecast_days = st.slider("미래 예측 기간 (일)", 10, 60, 20)
    simulations = st.slider("시뮬레이션 횟수", 1000, 50000, 2000)
    run_btn = st.button("🚀 분석 실행")

st.markdown(f"**대상:** {tickers} | **투자금:** {investment:,}원")

tab1, tab2, tab3 = st.tabs(["📊 데이터", "🔍 상관관계", "🎲 시뮬레이션"])

if run_btn:
    market_df = get_merged_market_data(tickers, period[0], period[1])
    
    if market_df is not None and not market_df.empty:
        market_df['Portfolio_KRW'] = 0 
        weight = investment / len(tickers) 
        base_prices = market_df[tickers].iloc[0]
        
        for t in tickers:
            if t in market_df.columns:
                stock_return = market_df[t] / base_prices[t] 
                exchange_return = market_df['USD_KRW'] / market_df['USD_KRW'].iloc[0] 
                market_df['Portfolio_KRW'] += (stock_return * exchange_return * weight) 
        
        # TAB 1: 데이터
        with tab1:
            st.subheader("원화 환산 포트폴리오 가치")
            st.line_chart(market_df['Portfolio_KRW'], use_container_width=True) 
            
            # [모바일] 데이터 표는 접어두기
            with st.expander("📋 상세 데이터 보기 (Click)", expanded=False):
                st.dataframe(market_df.tail(), use_container_width=True) 

        # TAB 2: 상관관계
        with tab2:
            st.subheader("자산 간 상관관계")
            analysis = tickers + ['USD_KRW']
            valid_cols = [c for c in analysis if c in market_df.columns]
            
            if len(valid_cols) > 1:
                corr = market_df[valid_cols].corr()
                fig, ax = plt.subplots()
                cax = ax.matshow(corr, cmap='coolwarm')
                fig.colorbar(cax)
                ax.set_xticks(range(len(valid_cols)))
                ax.set_yticks(range(len(valid_cols)))
                ax.set_xticklabels(valid_cols, rotation=45)
                ax.set_yticklabels(valid_cols)
                st.pyplot(fig, use_container_width=True)
                st.caption("🔴 빨강: 같이 움직임 / 🔵 파랑: 반대로 움직임")
            else:
                st.warning("데이터가 부족합니다.")

        # TAB 3: 시뮬레이션
        with tab3:
            st.subheader(f"몬테카를로 시뮬레이션 ({forecast_days}일 후)")
            daily_returns = np.log(market_df['Portfolio_KRW'] / market_df['Portfolio_KRW'].shift(1)).dropna()
            
            if not daily_returns.empty:
                current_value = market_df['Portfolio_KRW'].iloc[-1]
                with st.spinner('미래를 예측하는 중...'):
                    sim_paths = run_monte_carlo(daily_returns, current_value, forecast_days, simulations)
                
                # 결과 메트릭
                final_values = sim_paths[-1, :]
                var_95 = np.percentile(final_values, 5)
                var_amount = current_value - var_95
                mean_val = np.mean(final_values)
                
                c1, c2 = st.columns(2)
                c1.metric("평균 예상 가치", f"{int(mean_val):,}원", delta=f"{int(mean_val-current_value):,}원")
                c2.metric("최대 손실(VaR)", f"-{int(var_amount):,}원", delta_color="inverse")
                
                st.divider()

                # 차트 1: 경로
                st.markdown("##### 🍝 예상 자산 경로")
                fig_sim, ax_sim = plt.subplots(figsize=(10, 6))
                ax_sim.plot(sim_paths[:, :100], alpha=0.1, color='blue')
                ax_sim.set_title(f"Simulation Paths")
                ax_sim.yaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}'))
                st.pyplot(fig_sim, use_container_width=True)
                
                # 차트 2: 분포
                st.markdown("##### 📉 최종 가치 분포")
                fig_hist, ax_hist = plt.subplots(figsize=(10, 4))
                ax_hist.hist(final_values, bins=50, color='skyblue', edgecolor='black', alpha=0.7)
                ax_hist.axvline(var_95, color='red', linestyle='--', label=f'95% VaR: {int(var_95):,}W')
                ax_hist.legend()
                ax_hist.xaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}'))
                st.pyplot(fig_hist, use_container_width=True)
            else:
                 st.error("데이터 부족")
    else:
        st.error("데이터를 불러오지 못했습니다.")
else:
    st.info("👈 사이드바에서 설정 후 [분석 실행]을 눌러주세요.")