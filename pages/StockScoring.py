import yfinance as yf
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pandas_ta as ta
import datetime as dt
import streamlit as st

def get_trading_intensity(ticker,start_date):
    data = yf.download(ticker,start=start_date, progress=False, auto_adjust=True)
    
    dailyChange = data['Close'].pct_change() #변동률
    cumChange = (1 + dailyChange).cumprod() - 1 #누적 변동률
    
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)
        
    if data.empty:
        st.error(f"'{ticker}'에 대한 데이터를 가져오는 데 실패했습니다. 티커를 확인해 주세요.")
        return None, None, None
    
    data.ta.sma(length=5, append=True)
    data.ta.sma(length=20, append=True)
    data.ta.sma(length=50, append=True)
    data.ta.sma(length=100, append=True)
    data.ta.sma(close='volume', length=700, append=True, col_names=('Average_Volume_700'))
    data.ta.rsi(length=14, append=True, col_names=('rsi_14'))
    
    latest_data = data.iloc[-1]
    latest_price=latest_data['Close']
    buy_score={'sma':0, 'rsi':0 ,'volume':0, 'drawdown':0}
    high = data['Close'][-365:].max()
    drawdown = (latest_price - high)/high * 100
    
    #반등 매매
    #RSI
    if latest_data['rsi_14'] <= 25:
        buy_score['rsi'] += 100
    elif latest_data['rsi_14'] <= 30:
        buy_score['rsi'] += 60
    elif latest_data['rsi_14'] <= 35:
        buy_score['rsi'] += 40
    elif latest_data['rsi_14'] <= 40:
        buy_score['rsi'] += 20
    
    #낙폭
    if drawdown <= -20:
        buy_score['drawdown'] += 50
    elif drawdown <= -10:
        buy_score['drawdown'] += 30
    elif drawdown <= -5:
        buy_score['drawdown'] += 20
    
    #이평선
    if latest_price >= latest_data['SMA_20'] and latest_price <= latest_data['SMA_5']:
        buy_score['sma'] += 30
    elif latest_price >= latest_data['SMA_50'] and latest_price <= latest_data['SMA_20']:
        buy_score['sma'] += 50
    elif latest_price >= latest_data['SMA_100'] and latest_price <= latest_data['SMA_50']:
        buy_score['sma'] += 80
    
    #역배열 이평선일 경우
    if latest_price <= latest_data['SMA_20']<= latest_data['SMA_50']<= latest_data['SMA_100']:
        buy_score['sma'] -= 120
    
    return buy_score, dailyChange, cumChange


# Streamlit
st.set_page_config(layout="wide")

if 'history' not in st.session_state:
    st.session_state.history = []

st.sidebar.header("최근 검색 기록")
if not st.session_state.history:
    st.sidebar.write("검색 기록이 없습니다.")
else:
    for item in st.session_state.history:
        st.sidebar.write(item)

ticker=st.text_input("분석할 티커를 입력하세요(한국 주식 예시:486450.KS): ")
period_days = st.number_input("분석 기간 (일): ")

if st.button('검색'):
    today=dt.datetime.now().date()
    period=today - dt.timedelta(days=period_days)
    
    if ticker:
        result,dailyChange,cumChange = get_trading_intensity(ticker,period)
    
        total = sum(result.values())
        
        st.subheader(f"{ticker.upper()}의 매수 강도 지표")
        
        if ticker not in st.session_state.history:
                st.session_state.history.insert(0, ticker)
        
        col, col2 = st.columns(2)
        with col:
            st.write(f'총점: {total}점')
            st.write(f'일간변동률: {dailyChange.iloc[-1].to_numpy()[0]*100:.2f}%')
            st.write(f'누적변동률: {cumChange.iloc[-1].to_numpy()[0]*100:.2f}%')
        with col2:
            st.write('세부 점수:')
            st.json(result)
    else:
        st.warning("티커를 입력해 주세요.")