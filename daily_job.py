import os
import io
import time
import smtplib
import requests
import toml
import google.generativeai as genai
from pypdf import PdfReader
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from supabase import create_client

# ==========================================
# 1. 환경 설정 (로컬/서버 하이브리드)
# ==========================================

# 1-1. Supabase & API Key 로드
try:
    # 1. 로컬 개발 환경 (.streamlit/secrets.toml)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(current_dir, ".streamlit", "secrets.toml")
    
    if os.path.exists(secrets_path):
        secrets = toml.load(secrets_path)
        SUPABASE_URL = secrets["supabase"]["SUPABASE_URL"]
        SUPABASE_KEY = secrets["supabase"]["SUPABASE_KEY"]
        GEMINI_API_KEY = secrets.get("google", {}).get("api_key") or os.environ.get("GEMINI_API_KEY")
        GOOGLE_SEARCH_API_KEY = secrets.get("google", {}).get("search_key") or os.environ.get("GOOGLE_SEARCH_API_KEY")
        SEARCH_ENGINE_ID = secrets.get("google", {}).get("search_engine_id") or os.environ.get("SEARCH_ENGINE_ID")
        GMAIL_USER = secrets["GMAIL"]["GMAIL_USER"]
        GMAIL_APP_PWD = secrets["GMAIL"]["GMAIL_APP_PWD"]
    else:
        # 2. GitHub Actions 환경 (os.environ)
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY")
        SEARCH_ENGINE_ID = os.environ.get("SEARCH_ENGINE_ID")
        GMAIL_USER = os.environ.get("GMAIL_USER")
        GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD")

    # 클라이언트 생성
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)

except Exception as e:
    print(f"❌ 설정 로드 실패: {e}")
    exit()

# 1-2. 검색 대상 설정
TARGET_SITES = [
    # 1. 글로벌 자산운용사 (인프라/PE 특화)
    "blackrock.com",    
    "macquarie.com",     
    "kkr.com",         
    "brookfield.com",    
    
    # 2. 글로벌 투자은행 (IB - Market Outlook)
    "goldmansachs.com", 
    "jpmorgan.com", 
    "morganstanley.com",
    "ubs.com",          
    
    # 3. 컨설팅 및 리서치 (산업 트렌드)
    "mckinsey.com", 
    "pwc.com",
    "bain.com",         
    "deloitte.com",    
    
    # 4. 국제기구 (거시경제/정책)
    "worldbank.org", 
    "adb.org",           
    "imf.org"            
]

SEARCH_KEYWORD = "Infrastructure Outlook"

# ==========================================
# 2. 핵심 기능 함수
# ==========================================

def get_subscribers_from_db(lang_code=None):
    """DB에서 활성 구독자 이메일 가져오기"""
    try:
        query = supabase.table("subscribers").select("email").eq("is_active", True)
        if lang_code:
            query = query.eq("language", lang_code)
        
        response = query.execute()
        return [row['email'] for row in response.data]
    except Exception as e:
        print(f"❌ 구독자 DB 조회 실패: {e}")
        return []

def search_pdf_reports(keyword, sites):
    """구글 커스텀 검색 API로 PDF 찾기"""
    if not GOOGLE_SEARCH_API_KEY or not SEARCH_ENGINE_ID:
        print("⚠️ 검색 API 키가 없어 검색을 건너뜁니다.")
        return []
        
    site_query = " OR ".join([f"site:{site}" for site in sites])
    final_query = f"{keyword} filetype:pdf ({site_query})"
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_SEARCH_API_KEY,
        'cx': SEARCH_ENGINE_ID,
        'q': final_query,
        'num': 10, # 상위 5개만 분석
        'dateRestrict': 'w1' # 최근 1주일
    }
    try:
        res = requests.get(url, params=params).json()
        return [{'title': i['title'], 'link': i['link']} for i in res.get('items', [])]
    except Exception as e:
        print(f"❌ 검색 실패: {e}")
        return []

def extract_text_fast(url):
    """PDF 텍스트 추출 (기존 코드 활용)"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        
        f = io.BytesIO(response.content)
        reader = PdfReader(f)
        text = ""
        for i in range(min(len(reader.pages), 10)): # 최대 10페이지만
            text += reader.pages[i].extract_text() or ""
        return text if len(text) > 500 else None
    except:
        return None

def generate_synthesis(summaries_text, lang='ko'):
    """여러 요약본을 하나로 종합 (언어 선택 가능)"""
    model = genai.GenerativeModel('gemini-2.5-flash') # 최신 모델 사용 권장
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    if lang == 'en':
        prompt = f"""
        You are a Chief Market Strategist. 
        Synthesize the following individual report summaries into a comprehensive "Global Market Daily Brief".
        
        [Input Data]:
        {summaries_text}
        
        [Output Format (Markdown)]:
        # 🌍 Global Market Synthesis ({today})
        ## 1. Executive Summary (1 sentence)
        ## 2. Key Trends
        ## 3. Risk Factors
        """
    else:
        prompt = f"""
        당신은 수석 애널리스트입니다.
        아래 개별 리포트 요약본들을 종합하여 하나의 '글로벌 마켓 데일리 브리핑'을 작성하십시오.
        
        [입력 데이터]:
        {summaries_text}
        
        [출력 양식 (Markdown)]:
        # 🌍 글로벌 마켓 종합 리포트 ({today})
        ## 1. 핵심 요약 (한 줄)
        ## 2. 주요 트렌드
        ## 3. 리스크 요인
        """
        
    try:
        res = model.generate_content(prompt)
        return res.text
    except Exception as e:
        return f"분석 실패: {e}"

def send_email_batch(subject, body, receivers):
    """이메일 발송"""
    if not receivers: return
    
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['Subject'] = subject
    # 숨은 참조(BCC)로 보냄 (개인정보 보호)
    msg['Bcc'] = ", ".join(receivers) 
    msg.attach(MIMEText(body, 'plain')) # 또는 'html'로 변경 가능

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PWD)
        server.send_message(msg)
        server.quit()
        print(f"✅ 이메일 발송 완료 ({len(receivers)}명)")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

# ==========================================
# 3. 메인 로직
# ==========================================
if __name__ == "__main__":
    print("🚀 QuantLab Daily Job 시작...")
    
    # 1. 리포트 검색
    reports = search_pdf_reports(SEARCH_KEYWORD, TARGET_SITES)
    
    collected_summaries = []
    
    # 2. 개별 리포트 요약 (중간 단계)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    for report in reports:
        print(f"Processing: {report['title']}...")
        text = extract_text_fast(report['link'])
        if text:
            # 개별 요약은 토큰 절약을 위해 짧게 수행
            res = model.generate_content(f"Summarize this financial report in 3 bullets:\n{text[:10000]}")
            collected_summaries.append(f"Title: {report['title']}\nLink: {report['link']}\nSummary: {res.text}")

    if collected_summaries:
        all_text = "\n\n".join(collected_summaries)
        
        # 3. [핵심] 한국어 & 영어 종합 리포트 생성
        final_ko = generate_synthesis(all_text, 'ko')
        final_en = generate_synthesis(all_text, 'en')
        
        # 4. DB에 저장 (오늘의 리포트)
        db_data = {
            "title": f"Global Market Synthesis ({datetime.now().strftime('%Y-%m-%d')})",
            "link": "Combined Sources", # 또는 첫 번째 링크
            "summary_ko": final_ko,
            "summary_en": final_en
        }
        supabase.table("daily_reports").insert(db_data).execute()
        print("💾 DB 저장 완료!")
        
        # 5. 이메일 발송 (언어별 분리 발송)
        korean_users = get_subscribers_from_db('ko')
        english_users = get_subscribers_from_db('en')
        
        if korean_users:
            send_email_batch("[QuantLab] 오늘의 글로벌 마켓 브리핑", final_ko, korean_users)
            
        if english_users:
            send_email_batch("[QuantLab] Daily Market Briefing", final_en, english_users)
            
    else:
        print("💤 오늘은 새로운 리포트가 없습니다.")