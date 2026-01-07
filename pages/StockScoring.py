import streamlit as st
import yfinance as yf
import pandas as pd
import datetime as dt
import matplotlib.pyplot as plt
import os,sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from sidebar import render_sidebar
render_sidebar()

# -----------------------------------------------------------
# 함수 정의 (매물대 및 로직)
# -----------------------------------------------------------
def calculate_volume_profile(data, bins=50):
    price_min = data['Close'].min()
    price_max = data['Close'].max()
    intervals = pd.cut(data['Close'], bins=bins)
    vol_profile = data.groupby(intervals)['Volume'].sum()
    return vol_profile, intervals

def get_current_bin_rank(current_price, vol_profile):
    target_bin = None
    for interval in vol_profile.index:
        if interval.left <= current_price <= interval.right:
            target_bin = interval
            break
    if target_bin is None: return 0, 0
    current_vol = vol_profile[target_bin]
    percentile = (vol_profile < current_vol).mean() * 100
    return current_vol, percentile

def get_trading_intensity(ticker, period_days):
    end_date = dt.datetime.now()
    start_date = end_date - dt.timedelta(days=period_days)
    try:
        data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)
        if data.empty: return None, None, None, None
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)

        data.ta.rsi(length=14, append=True)
        data.ta.sma(length=5, append=True)
        data.ta.sma(length=20, append=True)
        vol_sma_20 = data['Volume'].rolling(window=20).mean()

        latest = data.iloc[-1]
        prev_1 = data.iloc[-2]
        prev_2 = data.iloc[-3]
        current_price = latest['Close']
        
        buy_score = {'volume_profile': 0, 'rsi': 0, 'price_drop': 0, 'volume_drop': 0}

        # 1. 매물대
        profile_data = data[-365:] if len(data) > 365 else data
        vol_profile, _ = calculate_volume_profile(profile_data)
        _, vol_rank = get_current_bin_rank(current_price, vol_profile)
        if vol_rank >= 80: buy_score['volume_profile'] += 30
        elif vol_rank >= 60: buy_score['volume_profile'] += 20
        elif vol_rank >= 40: buy_score['volume_profile'] += 10
        
        # 2. RSI
        rsi = latest['RSI_14']
        if rsi <= 25: buy_score['rsi'] += 30
        elif rsi <= 30: buy_score['rsi'] += 25
        elif rsi <= 35: buy_score['rsi'] += 15
        elif rsi <= 40: buy_score['rsi'] += 5

        # 3. 주가 하락
        price_5days_ago = data['Close'].iloc[-6] if len(data) > 6 else data['Close'].iloc[0]
        if (latest['Close'] < prev_1['Close']) and (prev_1['Close'] < prev_2['Close']): buy_score['price_drop'] += 20
        elif current_price < price_5days_ago: buy_score['price_drop'] += 10

        # 4. 거래량 감소
        vol_avg = vol_sma_20.iloc[-1]
        current_vol = latest['Volume']
        if current_vol < (vol_avg * 0.6): buy_score['volume_drop'] += 20
        elif current_vol < (vol_avg * 0.8): buy_score['volume_drop'] += 15
        elif current_vol < vol_avg: buy_score['volume_drop'] += 5

        daily_change = (current_price - prev_1['Close']) / prev_1['Close']
        return buy_score, daily_change, vol_profile, data
    except Exception as e:
        st.error(f"오류: {e}")
        return None, None, None, None

# -----------------------------------------------------------
# UI 구성
# -----------------------------------------------------------
st.title("🎯 매수 타점 분석기")

# [모바일 친화적 입력창] 메인 화면에 검색창 배치
with st.container():
    col_search1, col_search2 = st.columns([3, 1])
    with col_search1:
        # 사이드바 대신 여기서 입력 가능
        main_ticker = st.text_input("종목 코드 입력", placeholder="예: TSLA, 005930.KS", label_visibility="collapsed")
    with col_search2:
        main_search_btn = st.button("분석")

st.markdown("""
<small>
1. <b>매물대:</b> 바닥 지지 확인 / 2. <b>RSI:</b> 과매도(30↓) 확인 <br>
3. <b>주가 조정:</b> 충분한 하락 / 4. <b>거래량:</b> 투매 진정 확인
</small>
""", unsafe_allow_html=True)

st.warning("⚠️ **전제:** 우상향할 수 있는 신뢰할 수 있는 우량주 기준입니다.")
st.divider()

# 사이드바 
with st.sidebar:
    st.header("🔍 설정")
    sidebar_ticker = st.text_input("티커 (사이드바)", value="TSLA").upper()
    sidebar_btn = st.button("분석 실행 (사이드바)")

# 실행 로직 
target_ticker = None
if main_search_btn and main_ticker:
    target_ticker = main_ticker.upper()
elif sidebar_btn:
    target_ticker = sidebar_ticker

if target_ticker:
    with st.spinner(f"'{target_ticker}' 분석 중..."):
        scores, day_chg, vol_profile, df = get_trading_intensity(target_ticker, 365)

    if scores:
        total_score = sum(scores.values())
        
        c1, c2 = st.columns([1, 1])
        with c1:
            st.metric("총점", f"{total_score}점", delta=f"{day_chg*100:.2f}%")
        with c2:
            if total_score >= 80: st.success("💎 강력 매수")
            elif total_score >= 60: st.info("✅ 매수 적기")
            elif total_score >= 40: st.warning("👀 관심 단계")
            else: st.error("✋ 관망 필요")
                
        # [모바일] 상세 점수표는 접어두기
        with st.expander("📊 상세 점수표 열어보기", expanded=False):
            score_df = pd.DataFrame(list(scores.items()), columns=['항목', '점수'])
            name_map = {'volume_profile': '매물대', 'rsi': 'RSI', 'price_drop': '조정', 'volume_drop': '거래량'}
            score_df['항목'] = score_df['항목'].map(name_map)
            st.dataframe(score_df, hide_index=True, use_container_width=True)

        st.markdown("#### 📉 차트 & 매물대")
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(df.index, df['Close'], label='Price', color='black', linewidth=1)
        current_price = df['Close'].iloc[-1]
        ax.axhline(current_price, color='red', linestyle='--', label='Current')
        
        # 매물대 그리기
        y_pos = [i.mid for i in vol_profile.index]
        counts = vol_profile.values
        ax2 = ax.twiny()
        ax2.barh(y_pos, counts, height=(y_pos[1]-y_pos[0])*0.8, alpha=0.3, color='orange')
        ax.set_title(f"{target_ticker} Volume Profile")
        ax.legend(loc='upper left')
        ax2.set_xticks([])
        
        st.pyplot(fig, use_container_width=True)
            
    else:
        st.error("데이터 조회 실패. 티커를 확인해주세요.")
elif not target_ticker:
    st.info("👆 위 입력창에 종목 코드를 입력해주세요.")