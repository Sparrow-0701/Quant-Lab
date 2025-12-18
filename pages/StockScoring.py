import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import datetime as dt
import matplotlib.pyplot as plt
import numpy as np

# -----------------------------------------------------------
# 1. 매물대(Volume Profile) 계산 함수
# -----------------------------------------------------------
def calculate_volume_profile(data, bins=50):
    """
    주가 데이터를 가격 구간(Bin)으로 나누고, 각 구간의 누적 거래량을 계산합니다.
    """
    # 1. 가격 구간 나누기
    price_min = data['Close'].min()
    price_max = data['Close'].max()
    
    # 가격대를 bins 개수만큼 쪼갬
    intervals = pd.cut(data['Close'], bins=bins)
    
    # 2. 각 구간별 거래량 합계 계산
    vol_profile = data.groupby(intervals)['Volume'].sum()
    
    return vol_profile, intervals

def get_current_bin_rank(current_price, vol_profile):
    """
    현재 가격이 속한 구간이 전체 매물대 중 상위 몇 %인지 계산 (거래량이 많을수록 지지/저항 강력)
    """
    # 현재 가격이 속하는 구간 찾기
    target_bin = None
    for interval in vol_profile.index:
        if interval.left <= current_price <= interval.right:
            target_bin = interval
            break
            
    if target_bin is None:
        return 0, 0 # 범위 밖

    # 해당 구간의 거래량
    current_vol = vol_profile[target_bin]
    
    # 전체 구간 중 순위 (백분위: 100에 가까울수록 가장 두터운 매물대)
    percentile = (vol_profile < current_vol).mean() * 100
    
    return current_vol, percentile

# -----------------------------------------------------------
# 2. 핵심 분석 로직
# -----------------------------------------------------------
def get_trading_intensity(ticker, period_days):
    end_date = dt.datetime.now()
    start_date = end_date - dt.timedelta(days=period_days)
    
    try:
        data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)
        
        if data.empty:
            return None, None, None, None

        # MultiIndex 컬럼 처리
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # 기술적 지표 계산
        data.ta.rsi(length=14, append=True)
        data.ta.sma(length=5, append=True) # 5일 이동평균 (단기 추세)
        data.ta.sma(length=20, append=True) # 20일 이동평균 (거래량 비교용)
        
        # 거래량 이동평균 (Volume SMA)
        vol_sma_20 = data['Volume'].rolling(window=20).mean()

        latest = data.iloc[-1]
        prev_1 = data.iloc[-2]
        prev_2 = data.iloc[-3]
        
        current_price = latest['Close']
        
        # --- [점수 계산] 총 100점 만점 ---
        buy_score = {
            'volume_profile': 0, # 매물대 (30점)
            'rsi': 0,            # RSI (30점)
            'price_drop': 0,     # 주가 하락세 (20점)
            'volume_drop': 0     # 거래량 감소 (20점)
        }

        # 1. [매물대] 현재 가격이 두터운 매물대(지지 구간)에 있는가?
        # 최근 1년치 데이터로 매물대 산정
        profile_data = data[-365:] if len(data) > 365 else data
        vol_profile, _ = calculate_volume_profile(profile_data)
        _, vol_rank = get_current_bin_rank(current_price, vol_profile)
        
        # 상위 40% 이상 두터운 구간에 있으면 점수 부여
        if vol_rank >= 80: buy_score['volume_profile'] += 30 # 가장 강력한 매물대
        elif vol_rank >= 60: buy_score['volume_profile'] += 20
        elif vol_rank >= 40: buy_score['volume_profile'] += 10
        
        # 2. [RSI] 30 이하인가? (과매도)
        rsi = latest['RSI_14']
        if rsi <= 25: buy_score['rsi'] += 30
        elif rsi <= 30: buy_score['rsi'] += 25
        elif rsi <= 35: buy_score['rsi'] += 15 # 기준보다 살짝 높지만 근접
        elif rsi <= 40: buy_score['rsi'] += 5

        # 3. [주가 하락세] 최근 며칠간 주가가 떨어졌는가?
        # 3일 연속 하락 or 5일 전보다 하락
        price_5days_ago = data['Close'].iloc[-6] if len(data) > 6 else data['Close'].iloc[0]
        
        is_consecutive_drop = (latest['Close'] < prev_1['Close']) and (prev_1['Close'] < prev_2['Close'])
        is_trend_drop = current_price < price_5days_ago
        
        if is_consecutive_drop: buy_score['price_drop'] += 20
        elif is_trend_drop: buy_score['price_drop'] += 10

        # 4. [거래량 감소] 거래량이 감소세거나 평균보다 적은가?
        # 현재 거래량이 20일 평균 거래량의 80% 미만이면 "거래량 마름(매도세 진정)"으로 판단
        vol_avg = vol_sma_20.iloc[-1]
        current_vol = latest['Volume']
        
        if current_vol < (vol_avg * 0.6): buy_score['volume_drop'] += 20 # 매우 적음
        elif current_vol < (vol_avg * 0.8): buy_score['volume_drop'] += 15 # 적음
        elif current_vol < vol_avg: buy_score['volume_drop'] += 5      # 평균 이하

        # 부가 정보
        daily_change = (current_price - prev_1['Close']) / prev_1['Close']
        
        return buy_score, daily_change, vol_profile, data

    except Exception as e:
        st.error(f"분석 중 오류 발생: {e}")
        return None, None, None, None


# -----------------------------------------------------------
# UI 구성
# -----------------------------------------------------------
st.title("🎯 매수 타점 분석기")
st.markdown("""
### 🛒 매수 기준 (Buying Criteria)
1. 매물대 지지: 현재 가격이 거래량이 많이 터진 구간(바닥 지지)인가?
2. RSI 과매도: RSI가 30 이하로 내려왔는가?
3. 주가 조정: 최근 며칠간 주가가 충분히 하락했는가?
4. 거래량 감소: 하락하면서 거래량이 줄어들고 있는가? (투매 진정)
""")

st.warning("우상향할 수 있는 신뢰할 수 있는 기업이라는 전제 하의 매수 기준입니다")

st.divider()

# 사이드바
with st.sidebar:
    st.header("🔍 종목 검색")
    ticker = st.text_input("티커 입력 (예: AAPL, TSLA, 005930.KS)", value="TSLA").upper()
    run_btn = st.button("분석 실행")

if run_btn:
    with st.spinner(f"'{ticker}' 차트와 매물대를 분석 중입니다..."):
        scores, day_chg, vol_profile, df = get_trading_intensity(ticker, 365) # 1년치 데이터 분석

    if scores:
        total_score = sum(scores.values())
        
        # 1. 점수 및 판정
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.metric("총점", f"{total_score}점", delta=f"{day_chg*100:.2f}% (전일비)")
            
            if total_score >= 80:
                st.success("💎 **강력 매수 기회**\n\n모든 조건이 완벽하게 부합합니다.")
            elif total_score >= 60:
                st.info("✅ **매수 적기**\n\n매물대 지지와 과매도가 확인됩니다.")
            elif total_score >= 40:
                st.warning("👀 **관심 단계**\n\n일부 조건만 만족합니다.")
            else:
                st.error("✋ **관망 필요**\n\n아직 바닥 신호가 약합니다.")
                
            st.write("---")
            st.markdown("#### 📊 세부 점수")
            score_df = pd.DataFrame(list(scores.items()), columns=['항목', '점수'])
            # 항목 이름 한글 매핑
            name_map = {
                'volume_profile': '매물대 지지',
                'rsi': 'RSI 과매도',
                'price_drop': '주가 조정',
                'volume_drop': '거래량 감소'
            }
            score_df['항목'] = score_df['항목'].map(name_map)
            st.dataframe(score_df, hide_index=True)

        # 2. 매물대 차트 시각화 (Matplotlib)
        with c2:
            st.markdown("#### 📉 매물대 & 주가 차트")
            
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # (1) 주가 차트
            ax.plot(df.index, df['Close'], label='Price', color='black', linewidth=1)
            
            # (2) 현재가 표시 (빨간 점선)
            current_price = df['Close'].iloc[-1]
            ax.axhline(current_price, color='red', linestyle='--', label=f'Current: {current_price:.2f}')
            
            # (3) 매물대 (Volume Profile) - 수평 히스토그램
            # Y축: 가격 구간, X축: 거래량 길이
            # 시각적으로 방해되지 않게 투명도(alpha) 조절하여 왼쪽에 그림
            
            # 매물대 데이터 가공
            y_pos = [i.mid for i in vol_profile.index] # 구간의 중간값
            counts = vol_profile.values
            
            # 거래량을 차트 X축 스케일에 맞게 정규화 (최대 거래량을 차트 너비의 30% 정도로)
            max_vol = max(counts)
            time_span = (df.index[-1] - df.index[0]).days # 전체 기간 일수
            scale_factor = time_span * 0.3 / max_vol 
            
            # 매물대 그리기 (ax2: X축을 공유하지 않고 별도로 그림)
            ax2 = ax.twiny() 
            ax2.barh(y_pos, counts, height=(y_pos[1]-y_pos[0])*0.8, alpha=0.3, color='orange', label='Volume Profile')
            
            # 축 설정
            ax.set_ylabel("Price")
            ax.set_title(f"{ticker} Volume Profile & Trend")
            ax.legend(loc='upper left')
            
            # 매물대 축(위쪽)은 숫자 안 보이게 숨김
            ax2.set_xticks([]) 
            
            st.pyplot(fig)
            st.caption("배경의 주황색 막대가 길수록 해당 가격대에서 거래가 많이 일어났음(강력한 지지/저항)을 의미합니다.")
            
    else:
        st.error("데이터 조회 실패. 티커를 확인해주세요.")
else:
    st.info("👈 사이드바에서 티커를 입력해주세요.")
