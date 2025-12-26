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
from datetime import datetime, timedelta, timezone # timezone 필수
from supabase import create_client

# ==========================================
# 1. 환경 설정
# ==========================================

# 한국 시간대(KST) 정의 - 서버에서도 한국 시간으로 뜨게 함
KST = timezone(timedelta(hours=9))

try:
    # 1. 로컬 개발 환경
    current_dir = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(current_dir, ".streamlit", "secrets.toml")
    
    if os.path.exists(secrets_path):
        secrets = toml.load(secrets_path)
        SUPABASE_URL = secrets["supabase"]["SUPABASE_URL"]
        SUPABASE_KEY = secrets["supabase"]["SUPABASE_KEY"]
        GEMINI_API_KEY = secrets.get("google", {}).get("GEMINI_API_KEY")
        GOOGLE_SEARCH_API_KEY = secrets.get("google", {}).get("GOOGLE_SEARCH_API_KEY")
        SEARCH_ENGINE_ID = secrets.get("google", {}).get("SEARCH_ENGINE_ID") 
        GMAIL_USER = secrets["GMAIL"]["GMAIL_USER"]
        GMAIL_APP_PWD = secrets["GMAIL"]["GMAIL_APP_PWD"]
    else:
        # 2. GitHub Actions 환경
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY")
        SEARCH_ENGINE_ID = os.environ.get("SEARCH_ENGINE_ID")
        GMAIL_USER = os.environ.get("GMAIL_USER")
        GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)

except Exception as e:
    print(f"❌ 설정 로드 실패: {e}")
    exit()

# 검색 대상 및 키워드
TARGET_SITES = [
    "blackrock.com", "macquarie.com", "kkr.com", "brookfield.com",
    "goldmansachs.com", "jpmorgan.com", "morganstanley.com", "ubs.com",
    "mckinsey.com", "pwc.com", "bain.com", "deloitte.com",
    "worldbank.org", "adb.org", "imf.org"
]
SEARCH_KEYWORD = "Infrastructure Outlook"

# ==========================================
# 2. 핵심 기능 함수
# ==========================================

def get_subscribers_from_db(lang_code=None):
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
        'num': 10,
        'dateRestrict': 'w1'
    }
    try:
        res = requests.get(url, params=params).json()
        return [{'title': i['title'], 'link': i['link']} for i in res.get('items', [])]
    except Exception as e:
        print(f"❌ 검색 실패: {e}")
        return []

def extract_text_fast(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        
        f = io.BytesIO(response.content)
        reader = PdfReader(f)
        text = ""
        for i in range(min(len(reader.pages), 10)):
            text += reader.pages[i].extract_text() or ""
        return text if len(text) > 500 else None
    except:
        return None

def generate_synthesis(summaries_text, lang='ko'):
    model = genai.GenerativeModel('gemini-2.5-flash') 
    
    # [수정] 날짜를 KST 기준으로 생성
    today_kst = datetime.now(KST).strftime('%Y-%m-%d')
    
    if lang == 'en':
        prompt = f"""
        Role: You are a Chief Market Strategist at a top-tier global investment bank.
        Task: Synthesize the following individual report summaries into a professional "Global Market Daily Brief".
        
        [Input Summaries]:
        {summaries_text}
        
        [Constraints]:
        1. Tone: Professional, analytical, and objective.
        2. Content: Focus on actionable investment insights, macro trends, and specific sectors mentioned.
        3. Structure: Use the Markdown format below strictly.
        
        [Output Format]:
        # 🌍 Global Market Synthesis ({today_kst})
        
        ## 🎯 Executive Summary
        (One clear sentence summarizing the most important market signal today.)
        
        ## 📈 Key Investment Trends
        * (Trend 1): (Detail with specific sectors/assets)
        * (Trend 2): (Detail with specific sectors/assets)
        
        ## ⚠️ Risk Factors
        (Briefly mention potential risks like inflation, geopolitical issues, etc.)
        """
    else:
        prompt = f"""
        역할: 당신은 글로벌 투자 은행의 수석 시장 전략가(Chief Market Strategist)입니다.
        임무: 아래 제공된 개별 리포트 요약본들을 종합하여, 투자자들을 위한 전문적인 '글로벌 마켓 데일리 브리핑'을 작성하십시오.
        
        [입력 데이터]:
        {summaries_text}
        
        [제약 사항]:
        1. 어조: 전문적이고 분석적이며 객관적인 태도를 유지하십시오.
        2. 내용: 단순한 사실 나열보다 '투자 인사이트', '유망 섹터', '구체적인 수치'에 집중하십시오.
        3. 형식: 아래 마크다운 양식을 엄격히 따르십시오.
        
        [출력 양식]:
        # 🌍 글로벌 마켓 종합 리포트 ({today_kst})
        
        ## 🎯 핵심 요약 (Executive Summary)
        (오늘 시장을 관통하는 가장 중요한 신호를 한 문장으로 요약)
        
        ## 📈 주요 투자 트렌드
        * (트렌드 1): (관련 섹터나 자산군을 포함하여 구체적으로 설명)
        * (트렌드 2): (관련 섹터나 자산군을 포함하여 구체적으로 설명)
        
        ## ⚠️ 리스크 요인
        (인플레이션, 지정학적 이슈 등 잠재적 위험 요소 언급)
        """
        
    try:
        res = model.generate_content(prompt)
        return res.text
    except Exception as e:
        return f"분석 실패: {e}"

def send_email_batch(subject, body, receivers):
    if not receivers: return
    
    msg = MIMEMultipart()
    sender_name = "RevolTac" 
    msg['From'] = f"{sender_name} <{GMAIL_USER}>"
    msg['Subject'] = subject
    msg['Bcc'] = ", ".join(receivers) 
    msg.attach(MIMEText(body, 'plain'))

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
    
    reports = search_pdf_reports(SEARCH_KEYWORD, TARGET_SITES)
    
    structured_summaries = [] 
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # 2. 개별 리포트 요약
    for report in reports:
        print(f"Processing: {report['title']}...")
        
        text = extract_text_fast(report['link'])
        
        if text:
            try:
                # 한국어 요약
                prompt_ko = f"""
                당신은 시니어 퀀트 애널리스트입니다. 다음 금융 텍스트를 분석하여 투자자에게 가장 중요한 정보를 3가지 포인트로 요약하십시오.
                [텍스트]: {text[:15000]}
                [요약 규칙]: 수치(%, $)와 구체적 종목/섹터명 포함. 한국어 작성.
                [출력 형식]:
                * **(핵심 주제)**: ...
                * **(주목할 섹터)**: ...
                * **(결론/제언)**: ...
                """
                res_ko = model.generate_content(prompt_ko)
                
                # 영어 요약
                prompt_en = f"""
                You are a Senior Quantitative Analyst. Analyze the following financial text and summarize the most critical information for investors into 3 bullet points.
                [Text]: {text[:15000]}
                [Rules]: Include numbers (%, $) and specific tickers/sectors. Write in English.
                [Output Format]:
                * **(Key Theme)**: ...
                * **(Sector Focus)**: ...
                * **(Actionable Insight)**: ...
                """
                res_en = model.generate_content(prompt_en)
                
                # DB 저장
                supabase.table("individual_reports").insert({
                    "title": report['title'],
                    "link": report['link'],
                    "summary_ko": res_ko.text,
                    "summary_en": res_en.text
                }).execute()
                
                structured_summaries.append({
                    "title": report['title'],
                    "link": report['link'],
                    "summary_ko": res_ko.text,
                    "summary_en": res_en.text
                })
                
                time.sleep(2) 
                
            except Exception as e:
                print(f"Error processing {report['title']}: {e}")

    if structured_summaries:
        all_text_en = "\n\n".join([f"Title: {s['title']}\nSummary: {s['summary_en']}" for s in structured_summaries])
        
        print("🤖 종합 리포트 생성 중...")
        final_ko = generate_synthesis(all_text_en, 'ko')
        final_en = generate_synthesis(all_text_en, 'en')
        
        # 날짜를 KST 기준으로 생성
        today_kst_str = datetime.now(KST).strftime('%Y-%m-%d')
        today_kst_md = datetime.now(KST).strftime('%m/%d')
        
        # DB 저장 
        db_data = {
            "title": f"Global Market Synthesis ({today_kst_str})",
            "link": "Combined Sources",
            "summary_ko": final_ko,
            "summary_en": final_en
        }
        supabase.table("daily_reports").insert(db_data).execute()
        print("💾 종합 리포트 DB 저장 완료!")

        # 메일 본문 조립
        def build_mail_body(synthesis, summaries, lang='ko'):
            body = f"{synthesis}\n\n"
            body += "=" * 40 + "\n\n"
            
            if lang == 'ko':
                body += "📚 [참고한 개별 리포트 원문 요약]\n\n"
                key = 'summary_ko'
            else:
                body += "📚 [Individual Report Summaries]\n\n"
                key = 'summary_en'

            for item in summaries:
                body += f"📌 {item['title']}\n"
                body += f"🔗 {item['link']}\n"
                body += f"{item[key]}\n" 
                body += "-" * 20 + "\n"
            
            return body

        # 메일 발송
        korean_users = get_subscribers_from_db('ko')
        if korean_users:
            body_ko = build_mail_body(final_ko, structured_summaries, 'ko')
            send_email_batch(f"[QuantLab] 오늘의 글로벌 마켓 브리핑 ({today_kst_md})", body_ko, korean_users)

        english_users = get_subscribers_from_db('en')
        if english_users:
            body_en = build_mail_body(final_en, structured_summaries, 'en')
            send_email_batch(f"[QuantLab] Daily Market Brief ({today_kst_md})", body_en, english_users)
            
    else:
        print("💤 처리된 리포트가 없습니다.")