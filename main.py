# main.py
import streamlit as st
import os

st.set_page_config(
    page_title="Seunggyu's Quant Lab",
    page_icon="💸",
    layout="wide"
)

st.title("💸 승규의 AI 퀀트 투자 연구소")
st.markdown("### Data-Driven Investment Insights powered by Gemini")

st.divider()

# GitHub Actions가 생성한 리포트 읽어오기
report_path = "data/daily_report.md"

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("📰 오늘의 글로벌 기관 리포트 요약")
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            report_content = f.read()
        st.markdown(report_content)
    else:
        st.info("아직 오늘의 리포트가 생성되지 않았습니다. (매일 아침 7시 업데이트)")

with col2:
    st.info("💡 **이 사이트 활용법**")
    st.markdown("""
    1. **좌측 사이드바**에서 메뉴를 선택하세요.
    2. **Market Simulation**: 환율/주가 상관관계 및 몬테카를로 시뮬레이션
    3. **Stock Scoring**: 기술적 지표 기반 매수 강도 채점
    """)
    
    st.success("📩 **뉴스레터 구독**")
    st.text_input("이메일을 입력하고 매일 아침 리포트를 받아보세요", placeholder="example@email.com")
    st.button("구독 신청")