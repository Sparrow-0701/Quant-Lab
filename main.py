import streamlit as st
import smtplib
from email.mime.text import MIMEText
from supabase import create_client
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------
# 1. 초기 설정 및 DB 연결
# ---------------------------------------------------------
st.set_page_config(
    page_title="Quant Lab",
    page_icon="💸",
    layout="wide"
)

# CSS 스타일
st.markdown("""
    <style>
    @media (min-width: 992px) {
        div[data-testid="stColumn"]:nth-of-type(2) {
            position: sticky;
            top: 6rem;
            z-index: 1000;
            height: fit-content;
        }
    }
    </style>
""", unsafe_allow_html=True)

# Supabase 연결
@st.cache_resource
def init_supabase():
    url = st.secrets["supabase"]["SUPABASE_URL"]
    key = st.secrets["supabase"]["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"DB 연결 실패: secrets.toml을 확인해주세요. ({e})")
    st.stop()

# ---------------------------------------------------------
# 2. 핵심 로직 함수
# ---------------------------------------------------------

def log_action(email, action_type):
    """subscription_logs 테이블에 기록 남기기"""
    try:
        supabase.table("subscription_logs").insert({
            "email": email,
            "action_type": action_type
        }).execute()
        print(f"Log saved: {email} - {action_type}")
    except Exception as e:
        print(f"로그 저장 실패: {e}")

def send_subscription_alert(new_email):
    """관리자에게 메일 발송"""
    try:
        sender = st.secrets["GMAIL"]["GMAIL_USER"]
        password = st.secrets["GMAIL"]["GMAIL_APP_PWD"]
        admin_email = "ksmsk0701@gmail.com"

        msg = MIMEText(f"DB에 새로운 구독자가 등록되었습니다!\n\n이메일: {new_email}")
        msg['Subject'] = f"🔔 신규 구독자: {new_email}"
        msg['From'] = sender
        msg['To'] = admin_email

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"메일 발송 에러: {e}")
        return False

def subscribe_user_to_db(email, language='ko'):
    try:
        KST = timezone(timedelta(hours=9))

        now_kst = datetime.now(KST)

        current_date = now_kst.strftime("%Y-%m-%d")
        
        data = {
            "email": email, 
            "is_active": True, 
            "language": language,
            "start_date": current_date, 
        }
        
        # upsert: 있으면 수정(재구독), 없으면 추가
        supabase.table("subscribers").upsert(data, on_conflict='email').execute()
        
        # 로그 기록 (여기에 정확한 시간이 찍힘)
        log_action(email, 'SUBSCRIBE')
        
        send_subscription_alert(email)
        return "success"

    except Exception as e:
        return f"error: {str(e)}"

def unsubscribe_user_from_db(email):
    try:
        # 1. 존재하는지 확인
        check = supabase.table("subscribers").select("*").eq("email", email).execute()
        if not check.data:
            return "not_found"

        KST = timezone(timedelta(hours=9))
        now_kst = datetime.now(KST)
        
        current_date = now_kst.strftime("%Y-%m-%d")

        supabase.table("subscribers").update({
            "is_active": False,
            "end_date": current_date
        }).eq("email", email).execute()
        
        # 로그 기록
        log_action(email, 'UNSUBSCRIBE')
        
        return "success"
        
    except Exception as e:
        return f"error: {str(e)}"

# ---------------------------------------------------------
# 3. UI 구성
# ---------------------------------------------------------

st.title("💸 AI 뉴스레터")
st.divider()

col1, col2 = st.columns([2, 1])

# [왼쪽] 리포트 영역
with col1:
    st.subheader("📰 오늘의 글로벌 기관 리포트")
    
    lang_option = st.radio("언어 선택 (Language)", ["🇰🇷 한국어", "🇺🇸 English"], horizontal=True)
    selected_lang_code = 'ko' if "한국어" in lang_option else 'en'
    
    try:
        db_response = supabase.table("daily_reports").select("*").order("created_at", desc=True).limit(1).execute()
        
        if db_response.data:
            latest_report = db_response.data[0]
            
            if selected_lang_code == 'ko':
                summary_text = latest_report.get('summary_ko', '한국어 요약이 없습니다.')
            else:
                summary_text = latest_report.get('summary_en', 'English summary not available.')
                
                st.markdown(summary_text)
            st.caption(f"🔗 [원본 리포트 보러가기]({latest_report['link']})")
            
        else:
            st.warning("아직 생성된 리포트가 없습니다. (DB가 비어있음)")
            
    except Exception as e:
        st.error(f"리포트를 불러오는 중 오류가 발생했습니다: {e}")

# [오른쪽] 사이드바 및 기능
with col2:
    st.info("💡 **QuantLab 활용법**")
    st.markdown("""
    1. **매일 아침 8시** 월가 리포트 요약 업데이트
    2. **MonteCarlo**: 포트폴리오 시뮬레이션
    3. **Stock Scoring**: AI 종목 점수 분석
    """)
    
    st.divider()
    
    tab_sub, tab_unsub = st.tabs(["📩 구독 신청", "👋 구독 취소"])
    
    # 1. 구독 신청 탭
    with tab_sub:
        with st.form(key='sub_form'):
            sub_email = st.text_input("이메일 주소", placeholder="example@email.com")
            pref_lang = st.selectbox("리포트 언어", ["Korean (한국어)", "English (영어)"])
            sub_btn = st.form_submit_button("무료 구독하기")
            
            if sub_btn:
                if "@" not in sub_email:
                    st.warning("이메일 형식이 올바르지 않습니다.")
                else:
                    lang_code = 'en' if "English" in pref_lang else 'ko'
                    
                    with st.spinner("DB 등록 중..."):
                        result = subscribe_user_to_db(sub_email, lang_code)
                        
                        if result == "success":
                            st.balloons()
                            st.success(f"환영합니다! '{sub_email}'님이 구독 리스트에 등록되었습니다.")
                        else:
                            st.error(f"오류 발생: {result}")

    # 2. 구독 취소 탭
    with tab_unsub:
        with st.form(key='unsub_form'):
            unsub_email = st.text_input("구독했던 이메일", placeholder="example@email.com")
            unsub_btn = st.form_submit_button("구독 취소하기")
            
            if unsub_btn:
                with st.spinner("처리 중..."):
                    result = unsubscribe_user_from_db(unsub_email)
                    if result == "success":
                        st.success("구독이 취소되었습니다. 언제든 다시 돌아오세요!")
                    elif result == "not_found":
                        st.warning("구독 정보를 찾을 수 없습니다.")
                    else:
                        st.error(f"오류 발생: {result}")

st.divider()
with st.sidebar:
    st.caption("☕ **Buy Me a Coffee**")
    buymeacoffee_url = "https://www.buymeacoffee.com/revoltac"
    st.markdown(f"""
        <div style="text-align:center;">
            <a href="{buymeacoffee_url}" target="_blank">
                <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" style="width: 150px;" >
            </a>
        </div>
    """, unsafe_allow_html=True)
    st.caption("문의: ksmsk0701@gmail.com")