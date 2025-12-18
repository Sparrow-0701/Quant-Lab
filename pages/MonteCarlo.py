import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import os

# 환율 데이터 수집 (CSV에서 읽기)
@st.cache_data(ttl=3600)
def get_exchange_data_from_csv(start_date, end_date):
    csv_path = "data/exchange_rates.csv"
    
    if not os.path.exists(csv_path):
        # 파일이 없을 경우 (아직 봇이 한 번도 안 돌았거나, 초기 데이터가 없을 때)
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(csv_path)
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        
        # 날짜 필터링
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
        
        if df.empty:
            return pd.DataFrame()

        if 'Adj Close' in df.columns:
            df = df['Adj Close']
        elif 'Close' in df.columns:
            df = df['Close']
        else:
            try:
                df = df.xs('Adj Close', axis=1, level=0)
            except KeyError:
                df = df.xs('Close', axis=1, level=0)

        if isinstance(df, pd.Series):
            df = df.to_frame(name=tickers[0])
            
        return df
    except Exception as e:
        st.error(f"주가 데이터 수집 에러: {e}")
        return pd.DataFrame()


# 두 함수 결합
def get_merged_market_data(tickers, start, end): 
    df_stock = get_stock_data(tickers, start, end)
    df_exchange = get_exchange_data_from_csv(start, end) 
    
    # 환율 데이터가 없거나 주식 데이터가 없으면 None 반환
    if df_stock.empty:
        st.warning("주식 데이터를 불러오지 못했습니다.")
        return None
        
    if df_exchange.empty:
        st.warning(f"해당 기간({start} ~ {end})의 환율 데이터가 없습니다. (GitHub 봇이 데이터를 수집 중입니다)")
        # 환율 데이터가 없으면 1200원으로 임시 고정하거나 에러 처리 (여기선 에러 처리)
        return None

    merged_df = df_stock.join(df_exchange, how='left')
    merged_df['USD_KRW'] = merged_df['USD_KRW'].ffill() # 주말 등 빈 날짜 채우기
    merged_df['USD_KRW'] = merged_df['USD_KRW'].bfill() # 앞부분이 비어있으면 뒤에서 채우기
    
    return merged_df


# 몬테카를로 시뮬레이션 함수
def run_monte_carlo(hist_returns, start_price, days, simulations):
    random_returns = np.random.choice(hist_returns, size=(days, simulations), replace=True)
    cum_returns = np.exp(np.cumsum(random_returns, axis=0))
    price_paths = np.zeros((days + 1, simulations))
    price_paths[0] = start_price
    price_paths[1:] = start_price * cum_returns
    return price_paths


#---------------------------------------UI-------------------------------------------

st.title("🛡️ Portfolio PathFinder (Monte Carlo)")

with st.sidebar:
    st.header("⚙️ 포트폴리오 설정")
    tickers_input = st.text_input("종목 티커 (쉼표 구분)", value="AAPL, GOOGL, NVDA")
    tickers = [t.strip().upper() for t in tickers_input.split(',')]
    
    investment = st.number_input("초기 투자금 (원화)", value=10000000, step=1000000)
    
    # [API 키 입력창 삭제됨] - 아주 깔끔합니다!
    
    period = st.date_input("과거 데이터 기간", value=(pd.to_datetime("2024-01-01"), pd.to_datetime("2024-12-01")))
    
    forecast_days = st.slider("미래 예측 기간 (일)", 10, 60, 20)
    simulations = st.slider("시뮬레이션 횟수", 1000, 50000, 2000)
    
    run_btn = st.button("🚀 분석 실행")

st.markdown(f"**대상:** {tickers} | **투자금:** {investment:,}원 | **분석모델:** Monte Carlo Simulation")

tab1, tab2, tab3 = st.tabs(["📊 데이터(Data)", "🔍 통계(Stats)", "🎲 시뮬레이션(VaR)"])

if run_btn:
    # 1. 데이터 수집 (인자 3개로 수정됨)
    market_df = get_merged_market_data(tickers, period[0], period[1])
    
    if market_df is not None and not market_df.empty:
        
        # 합성 포트폴리오 만들기
        market_df['Portfolio_KRW'] = 0 
        weight = investment / len(tickers) 
        
        base_prices = market_df[tickers].iloc[0]
        
        for t in tickers:
            if t in market_df.columns:
                stock_return = market_df[t] / base_prices[t] 
                exchange_return = market_df['USD_KRW'] / market_df['USD_KRW'].iloc[0] 
                market_df['Portfolio_KRW'] += (stock_return * exchange_return * weight) 
        
        # ---------------- TAB 1 ----------------
        with tab1:
            st.subheader("1. 원화 환산 포트폴리오 가치 추이")
            st.line_chart(market_df['Portfolio_KRW']) 
            st.write("💡 **상세 데이터 (최근 5일)**")
            st.dataframe(market_df.tail()) 

        # ---------------- TAB 2----------------
        with tab2:
            st.subheader("2. 자산 간 상관관계 히트맵")
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
                st.pyplot(fig)
                st.info("빨간색에 가까울수록 같이 움직이고, 파란색일수록 반대로 움직입니다.")
            else:
                st.warning("상관관계를 계산할 충분한 데이터가 없습니다.")

        # ---------------- TAB 3----------------
        with tab3:
            st.subheader(f"3. 몬테카를로 시뮬레이션 (향후 {forecast_days}일)")
            
            daily_returns = np.log(market_df['Portfolio_KRW'] / market_df['Portfolio_KRW'].shift(1)).dropna()
            
            if not daily_returns.empty:
                current_value = market_df['Portfolio_KRW'].iloc[-1]
                
                with st.spinner(f'{simulations}개의 미래를 생성하는 중...'):
                    sim_paths = run_monte_carlo(daily_returns, current_value, forecast_days, simulations)
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.markdown("##### 🍝 예상 자산 경로 (상위 100개 샘플)")
                    fig_sim, ax_sim = plt.subplots(figsize=(10, 6))
                    ax_sim.plot(sim_paths[:, :100], alpha=0.1, color='blue')
                    ax_sim.set_title(f"Monte Carlo Paths ({simulations} Simulations)")
                    ax_sim.set_xlabel("Days")
                    ax_sim.set_ylabel("Portfolio Value (KRW)")
                    ax_sim.yaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}'))
                    st.pyplot(fig_sim)
                
                with col2:
                    final_values = sim_paths[-1, :]
                    var_95_value = np.percentile(final_values, 5)
                    var_amount = current_value - var_95_value
                    mean_value = np.mean(final_values)
                    
                    st.markdown("### 📊 분석 결과")
                    st.metric(label="현재 가치", value=f"{int(current_value):,}원")
                    st.metric(label="평균 예상 가치", value=f"{int(mean_value):,}원",delta=f"{int(mean_value - current_value):,}원")
                    st.divider()
                    st.markdown(f"#### ⚠️ 95% VaR ({forecast_days}일)")
                    st.error(f"최대 예상 손실: -{int(var_amount):,}원")
                    st.caption(f"95% 확률로 포트폴리오 가치는 **{int(var_95_value):,}원** 이상을 유지합니다.")
                    
                st.markdown("##### 📉 최종 자산 가치 분포도")
                fig_hist, ax_hist = plt.subplots(figsize=(10, 4))
                ax_hist.hist(final_values, bins=50, color='skyblue', edgecolor='black', alpha=0.7)
                ax_hist.axvline(var_95_value, color='red', linestyle='dashed', linewidth=2, label=f'95% VaR: {int(var_95_value):,}W')
                ax_hist.legend()
                ax_hist.xaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}'))
                st.pyplot(fig_hist)
            else:
                 st.error("수익률을 계산할 데이터가 부족합니다.")

    else:
        st.error("데이터를 불러오지 못했습니다. 환율 데이터(CSV)가 있는지 확인해주세요.")

else:
    st.info("👈 사이드바에서 설정 후 [분석 실행]을 눌러주세요.")
