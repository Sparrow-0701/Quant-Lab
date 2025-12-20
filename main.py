import streamlit as st
import os
import smtplib
from email.mime.text import MIMEText
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta,timezone


st.set_page_config(
    page_title="Quant Lab",
    page_icon="💸",
    layout="wide"
    
)

st.markdown("""
    <style>
    @media (min-width: 992px) {
        div[data-testid="stColumn"]:nth-of-type(2) {
            position: sticky;
            top: 6rem; 
            =
            z-index: 1000;
            height: fit-content;
        }
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 구독자 알림 메일 보내는 함수
# ---------------------------------------------------------
def send_subscription_alert(new_email):
    # Streamlit Secrets에서 계정 정보 가져오기
    try:
        sender = st.secrets["GMAIL_USER"]
        password = st.secrets["GMAIL_APP_PWD"]
    except:
        # 로컬 환경이나 시크릿이 없을 경우 예외 처리
        st.error("메일 설정(Secrets)이 되어있지 않습니다.")
        return False

    admin_email = "ksmsk0701@gmail.com"

    # 메일 내용 작성
    msg = MIMEText(f"새로운 뉴스레터 구독 신청이 들어왔습니다!\n\n구독자 이메일: {new_email}\n\n*GitHub Secrets에 이분을 추가해주세요!*")
    msg['Subject'] = f"🔔 신규 구독자 알림: {new_email}"
    msg['From'] = sender
    msg['To'] = admin_email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"메일 전송 오류: {e}")
        return False
    
def unsubscribe_user(email):
    try:
        # 1. 인증 및 연결
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = st.secrets["gcp_service_account"] 
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        # 파일명 확인
        sheet = client.open("QuantLab Subscribers").sheet1
        
        # 2. 모든 데이터 가져오기
        rows = sheet.get_all_values()
        
        target_row_index = None
        
        # 3. 반복문을 돌며 진짜 취소해야 할 행 찾기
        # (헤더가 있으므로 인덱스 1부터 시작)
        for i in range(1, len(rows)):
            row = rows[i]
            
            # 데이터 가져오기 (인덱스 에러 방지)
            r_email = row[0].strip() if len(row) > 0 else ""
            r_cancel_time = row[4].strip() if len(row) > 4 else "" # E열 값
            
            # [핵심 조건] 이메일이 같고 + "취소 날짜가 비어 있어야" 함
            if r_email == email and r_cancel_time == "":
                target_row_index = i + 1 # 리스트 인덱스(0부터) -> 엑셀 행 번호(1부터)로 변환
                break # 찾았으면 중단
        
        # 4. 결과 처리
        if target_row_index:
            # 한국 시간 구하기
            kst = timezone(timedelta(hours=9))
            cancel_time = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
            
            # 정확히 찾은 그 줄의 5번째 칸만 업데이트
            sheet.update_cell(target_row_index, 5, cancel_time) 
            return "success"
        else:
            # 이메일은 있어도 이미 다 취소된 상태라면 'not_found' 취급
            return "not_found"
            
    except Exception as e:
        st.error(f"구독 취소 오류: {e}")
        return "error"
    
def save_to_google_sheet(email):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = st.secrets["gcp_service_account"] 
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        sheet = client.open("QuantLab Subscribers").sheet1
        
        try:
            rows = sheet.get_all_values()
        except:
            rows = []
        
        # [수정] 한국 시간(KST) 기준 날짜 생성
        kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(kst)
        today = now_kst.strftime("%Y-%m-%d")
        
        # 중복 여부 확인
        is_active_subscriber = False
        
        if len(rows) > 1: 
            for row in rows[1:]:
                r_email = row[0].strip() if len(row) > 0 else ""
                r_end_date = row[2].strip() if len(row) > 2 else ""
                r_cancel_time = row[4].strip() if len(row) > 4 else "" 
                
                if r_email == email:
                    if r_cancel_time == "" and r_end_date >= today:
                        is_active_subscriber = True
                        break 

        if is_active_subscriber:
            return "duplicate"
            
        else:
            next_row = len(rows) + 1 
            
            if sheet.row_count < next_row:
                sheet.resize(rows=next_row)
            
            # [수정] 한국 시간 기준으로 날짜 계산
            next_year = (now_kst + timedelta(days=365)).strftime("%Y-%m-%d")
            now_time = now_kst.strftime("%Y-%m-%d %H:%M:%S")
            
            sheet.update_cell(next_row, 1, email)       # Email
            sheet.update_cell(next_row, 2, today)       # Start_Date (KST)
            sheet.update_cell(next_row, 3, next_year)   # End_Date (KST)
            sheet.update_cell(next_row, 4, now_time)    # Register_Time (KST)
            sheet.update_cell(next_row, 5, "")          
            
            return "success"
        
    except Exception as e:
        st.error(f"상세 에러 내용: {str(e)}")
        return "error"
    
# ---------------------------------------------------------


st.title("💸 AI 퀀트 투자 연구소")

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
        st.info("아직 오늘의 리포트가 생성되지 않았습니다. (매일 아침 8시 업데이트)")

with col2:
    st.info("💡 **이 사이트 활용법**")
    st.markdown("""
    1. **좌측 사이드바**를 여세요. (`>`)
    2. **MonteCarlo**: 환율/주가 시뮬레이션
    3. **Stock Scoring**: 매수 타점 분석
    """)
    
    st.divider()
    
    # 탭으로 구독/취소 분리
    tab_sub, tab_unsub = st.tabs(["📩 구독 신청", "👋 구독 취소"])
    
    # 1. 구독 신청 탭
    with tab_sub:
        with st.form(key='sub_form'):
            sub_email = st.text_input("이메일 입력", placeholder="example@email.com")
            sub_btn = st.form_submit_button("구독하기")
            
            if sub_btn:
                if "@" not in sub_email:
                    st.warning("올바른 이메일을 입력해주세요.")
                else:
                    with st.spinner("확인 중..."):
                        clean_email = sub_email.strip()
                        result = save_to_google_sheet(clean_email)
                        
                        if result == "success":
                            st.balloons()
                            st.success(f"🎉 환영합니다! '{clean_email}' 님, 구독 리스트에 등록되었습니다.")
                        elif result == "duplicate":
                            st.warning(f"😅 '{clean_email}' 님은 현재 구독 중입니다.")
                        elif result == "resubscribed":
                            st.balloons()
                            st.info(f"👋 다시 돌아오셨군요! '{clean_email}' 님의 구독이 새로 시작됩니다.")
                        else:
                            st.error("오류가 발생했습니다.")

    # 2. 구독 취소 탭 
    with tab_unsub:
        st.caption("더 이상 리포트를 받고 싶지 않으신가요? 😢")
        with st.form(key='unsub_form'):
            unsub_email = st.text_input("구독했던 이메일 입력", placeholder="example@email.com")
            unsub_btn = st.form_submit_button("구독 취소하기")
            
            if unsub_btn:
                if "@" not in unsub_email:
                    st.warning("이메일을 정확히 입력해주세요.")
                else:
                    with st.spinner("처리 중..."):
                        result = unsubscribe_user(unsub_email)
                        
                        if result == "success":
                            st.success("구독이 취소되었습니다. 더 이상 메일이 발송되지 않습니다.")
                        elif result == "not_found":
                            st.error("구독 리스트에 없는 이메일입니다.")
                        else:
                            st.error("오류가 발생했습니다.")

st.divider()
st.caption("⚠️ **Disclaimer**: 본 서비스는 모의 투자 및 연구 목적으로 제작되었으며, 실제 투자에 대한 법적 책임을 지지 않습니다. 모든 데이터는 실시간이 아닐 수 있습니다.")

with st.sidebar:
    st.caption("☕ **개발자에게 커피 한 잔 쏘기**")
    
    buymeacoffee_url = "https://www.buymeacoffee.com/revoltac"
    
    st.markdown(
        f"""
        <div style="text-align:center;">
            <a href="{buymeacoffee_url}" target="_blank">
                <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 200px !important;" >
            </a>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.caption("서버 비용과 개발에 큰 힘이 됩니다!")
    
    st.caption("문의사항: ksmsk0701@gmail.com")
