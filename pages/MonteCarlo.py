import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import os
import sys
from supabase import create_client
import toml

# ------------------------------------------------------------------
# 1. 경로 설정 (로컬/서버 호환)
# ------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from sidebar import render_sidebar

# ------------------------------------------------------------------
# 2. 페이지 설정 및 사이드바 로드
# ------------------------------------------------------------------
st.set_page_config(page_title="포트폴리오 시뮬레이션", page_icon="🎲", layout="wide")
render_sidebar()

# ------------------------------------------------------------------
# 3. Supabase 연결 (안전한 시크릿 로드)
# ------------------------------------------------------------------
@st.cache_resource
def init_supabase():
    # 1. Streamlit Cloud Secrets 우선 확인
    try:
        url = st.secrets["supabase"]["SUPABASE_URL"]
        key = st.secrets["supabase"]["SUPABASE_KEY"]
        return create_client(url, key)
    except:
        pass

    # 2. 로컬 secrets.toml 확인
    try:
        secrets_path = os.path.join(parent_dir, ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            secrets = toml.load(secrets_path)
            return create_client(secrets["supabase"]["SUPABASE_URL"], secrets["supabase"]["SUPABASE_KEY"])
    except:
        pass
    
    # 3. 환경변수 확인
    return create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

try:
    supabase = init_supabase()
except Exception as e:
    st.error("DB 연결 실패. API 키를 확인해주세요.")
    st.stop()

# ------------------------------------------------------------------
# 4. 데이터 수집 및 전처리 함수
# ------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_stock_data(tickers, start_date, end_date):
    """야후 파이낸스에서 주가 데이터 수집"""
    try:
        df = yf.download(tickers, start=start_date, end=end_date, progress=False, auto_adjust=False)
        
        if df.empty: return pd.DataFrame()

        # MultiIndex 처리 (yfinance 최신 버전 대응)
        if 'Adj Close' in df.columns:
            df = df['Adj Close']
        elif 'Close' in df.columns:
            df = df['Close']
            
        # 단일 종목일 경우 Series를 DataFrame으로 변환
        if isinstance(df, pd.Series):
            df = df.to_frame(name=tickers[0])
            
        # 인덱스(날짜) 시간대 제거 (Timezone-naive)
        df.index = df.index.tz_localize(None)
        return df
    except Exception as e:
        st.error(f"주가 데이터 수집 실패: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_exchange_rate_from_db(start_date, end_date):
    """Supabase에서 환율 데이터를 가져와 DataFrame으로 가공"""
    try:
        # [수정됨] 사용자의 테이블 구조에 맞춰 쿼리 변경 (ticker 필터 제거, usd_krw 사용)
        response = supabase.table("exchange_rates")\
            .select("date, usd_krw")\
            .gte("date", start_date)\
            .lte("date", end_date)\
            .order("date", desc=False)\
            .execute()
        
        data = response.data
        if not data:
            return pd.DataFrame()

        # DataFrame 변환 및 전처리
        df = pd.DataFrame(data)
        # date 컬럼을 날짜 형식으로 변환
        df['date'] = pd.to_datetime(df['date']).dt.normalize() 
        df = df.set_index('date')
        
        # 컬럼 이름 통일 (usd_krw -> USD_KRW)
        if 'usd_krw' in df.columns:
            df = df.rename(columns={'usd_krw': 'USD_KRW'})
        
        # 중복 날짜 제거 (하루에 여러 데이터가 있을 경우 마지막 값 사용)
        df = df[~df.index.duplicated(keep='last')]
        
        return df
    except Exception as e:
        st.error(f"환율 데이터 조회 실패: {e}")
        return pd.DataFrame()

def get_merged_market_data(tickers, start, end):
    # 1. 주식 데이터
    df_stock = get_stock_data(tickers, start, end)
    if df_stock.empty:
        st.warning("주식 데이터를 불러오지 못했습니다.")
        return None

    # 2. 환율 데이터
    df_exchange = get_exchange_rate_from_db(str(start), str(end))
    
    # 환율 데이터가 없으면 1,400원으로 가정하고 경고 (에러 방지용)
    if df_exchange.empty:
        st.warning("⚠️ 기간 내 환율 데이터가 없어 고정 환율(1,400원)로 대체합니다.")
        # 주식 데이터 인덱스에 맞춰 고정 환율 데이터 생성
        df_exchange = pd.DataFrame({'USD_KRW': 1400.0}, index=df_stock.index)

    # 3. 데이터 병합 (날짜 기준 Left Join)
    # 주식 거래일 기준으로 환율 데이터를 붙입니다.
    merged_df = df_stock.join(df_exchange, how='left')
    
    # 4. 결측치 채우기 (주말/공휴일 환율은 직전일 데이터 사용 -> 없으면 다음날 데이터 사용)
    merged_df['USD_KRW'] = merged_df['USD_KRW'].ffill().bfill()
    
    return merged_df

def run_monte_carlo(hist_returns, start_price, days, simulations):
    """몬테카를로 시뮬레이션 엔진"""
    # 과거 수익률에서 무작위 추출
    random_returns = np.random.choice(hist_returns, size=(days, simulations), replace=True)
    
    # 누적 수익률 계산
    cum_returns = np.exp(np.cumsum(random_returns, axis=0))
    
    # 가격 경로 생성
    price_paths = np.zeros((days + 1, simulations))
    price_paths[0] = start_price
    price_paths[1:] = start_price * cum_returns
    return price_paths

# ------------------------------------------------------------------
# 5. UI 구성
# ------------------------------------------------------------------

st.title("🛡️ Portfolio PathFinder")
st.info("👈 **왼쪽 사이드바**를 열어 종목과 투자금을 설정하세요!")

with st.sidebar:
    st.header("⚙️ 포트폴리오 설정")
    default_tickers = "AAPL, MSFT, NVDA"
    tickers_input = st.text_input("미국 주식 티커 (쉼표 구분)", value=default_tickers)
    tickers = [t.strip().upper() for t in tickers_input.split(',') if t.strip()]
    
    investment = st.number_input("초기 투자금 (원화)", value=10000000, step=1000000, format="%d")
    
    # 날짜 기본값 설정
    today = pd.Timestamp.now().date()
    start_default = today - pd.Timedelta(days=365)
    period = st.date_input("과거 데이터 기간", value=(start_default, today))
    
    st.divider()
    forecast_days = st.slider("미래 예측 기간 (일)", 10, 90, 30)
    simulations = st.slider("시뮬레이션 횟수", 1000, 50000, 2000)
    
    run_btn = st.button("🚀 분석 실행", type="primary")

# 실행 로직
if run_btn:
    if len(period) != 2:
        st.error("시작일과 종료일을 모두 선택해주세요.")
    else:
        st.markdown(f"**분석 대상:** {', '.join(tickers)} | **투자금:** {investment:,}원")
        
        with st.spinner("데이터를 수집하고 시뮬레이션을 돌리는 중..."):
            market_df = get_merged_market_data(tickers, period[0], period[1])

        if market_df is not None:
            # 포트폴리오 가치 계산 (동일 비중 가정)
            market_df['Portfolio_KRW'] = 0 
            weight = investment / len(tickers)
            
            # 기준일 가격 (첫 날)
            base_prices = market_df[tickers].iloc[0]
            base_exchange = market_df['USD_KRW'].iloc[0]
            
            for t in tickers:
                if t in market_df.columns:
                    # 주가 수익률 * 환율 수익률 * 투자금(종목별)
                    # NaN 값 방지를 위해 fillna(0) 추가 고려 가능하나, 여기선 데이터가 있다는 전제로 진행
                    stock_return = market_df[t] / base_prices[t]
                    exchange_return = market_df['USD_KRW'] / base_exchange
                    market_df['Portfolio_KRW'] += (stock_return * exchange_return * weight)

            # 탭 구성
            tab1, tab2, tab3 = st.tabs(["📊 데이터 & 차트", "🔍 상관관계", "🎲 시뮬레이션"])

            # TAB 1: 데이터
            with tab1:
                st.subheader("💰 원화 환산 포트폴리오 가치 추이")
                st.line_chart(market_df['Portfolio_KRW'], color="#FF4B4B")
                
                with st.expander("📋 일자별 상세 데이터 보기"):
                    st.dataframe(market_df.style.format("{:,.0f}"), use_container_width=True)

            # TAB 2: 상관관계
            with tab2:
                st.subheader("🔗 자산 간 상관관계 (Heatmap)")
                # 분석 대상: 개별 주식 + 환율
                analysis_cols = [c for c in tickers if c in market_df.columns] + ['USD_KRW']
                
                if len(analysis_cols) > 1:
                    corr = market_df[analysis_cols].corr()
                    
                    fig, ax = plt.subplots(figsize=(8, 6))
                    cax = ax.matshow(corr, cmap='RdBu_r', vmin=-1, vmax=1) # 색상 개선
                    fig.colorbar(cax)
                    
                    ax.set_xticks(range(len(analysis_cols)))
                    ax.set_yticks(range(len(analysis_cols)))
                    ax.set_xticklabels(analysis_cols, rotation=45)
                    ax.set_yticklabels(analysis_cols)
                    
                    # 상관계수 숫자 표시
                    for (i, j), z in np.ndenumerate(corr):
                        ax.text(j, i, '{:0.2f}'.format(z), ha='center', va='center', color='black')
                        
                    st.pyplot(fig, use_container_width=False)
                else:
                    st.info("종목이 2개 이상이어야 상관관계를 분석할 수 있습니다.")

            # TAB 3: 시뮬레이션
            with tab3:
                st.subheader(f"🎲 몬테카를로 시뮬레이션 ({forecast_days}일 후)")
                
                # 로그 수익률 계산 (시뮬레이션용)
                daily_returns = np.log(market_df['Portfolio_KRW'] / market_df['Portfolio_KRW'].shift(1)).dropna()
                
                if not daily_returns.empty:
                    current_value = market_df['Portfolio_KRW'].iloc[-1]
                    
                    # 시뮬레이션 실행
                    sim_paths = run_monte_carlo(daily_returns.values, current_value, forecast_days, simulations)
                    
                    # 통계 계산
                    final_values = sim_paths[-1, :]
                    mean_val = np.mean(final_values)
                    var_95 = np.percentile(final_values, 5) # 하위 5%
                    risk_amount = current_value - var_95
                    
                    # 결과 카드 표시
                    col_res1, col_res2 = st.columns(2)
                    col_res1.metric(
                        label="평균 예상 가치", 
                        value=f"{int(mean_val):,}원", 
                        delta=f"{int(mean_val/current_value * 100 - 100):.1f}% 수익 예상"
                    )
                    col_res2.metric(
                        label="95% VaR (최대 손실 위험)", 
                        value=f"-{int(risk_amount):,}원", 
                        delta="하위 5% 최악의 경우",
                        delta_color="inverse"
                    )
                    
                    st.divider()

                    # 시각화
                    col_chart1, col_chart2 = st.columns(2)
                    
                    with col_chart1:
                        st.markdown("**🍝 시나리오 경로 (100개 샘플)**")
                        fig_sim, ax_sim = plt.subplots(figsize=(6, 4))
                        ax_sim.plot(sim_paths[:, :100], alpha=0.1, color='#1f77b4')
                        ax_sim.axhline(current_value, color='black', linestyle='--', alpha=0.5)
                        ax_sim.set_title("Asset Paths")
                        ax_sim.yaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}'))
                        st.pyplot(fig_sim)

                    with col_chart2:
                        st.markdown("**📉 최종 가치 분포도**")
                        fig_hist, ax_hist = plt.subplots(figsize=(6, 4))
                        ax_hist.hist(final_values, bins=50, color='#ff7f0e', edgecolor='white', alpha=0.8)
                        ax_hist.axvline(var_95, color='red', linestyle='--', linewidth=2, label='95% VaR')
                        ax_hist.axvline(current_value, color='black', linestyle='-', linewidth=1, label='Current')
                        ax_hist.legend()
                        ax_hist.xaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}'))
                        st.pyplot(fig_hist)
                        
                else:
                    st.error("수익률을 계산할 데이터가 부족합니다.")
else:
    # 초기 화면 가이드
    st.markdown(
        """
        <div style="text-align: center; padding: 50px;">
            <h3>👈 왼쪽 사이드바에서 설정을 완료해주세요</h3>
            <p style="color: gray;">원하는 미국 주식 티커와 기간을 입력하면,<br>
            환율까지 고려한 원화 기준 포트폴리오 시뮬레이션을 제공합니다.</p>
        </div>
        """, unsafe_allow_html=True
    )