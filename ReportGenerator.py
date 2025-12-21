import os
import io
import time
import smtplib
import requests
import google.generativeai as genai
from pypdf import PdfReader
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials 

# ==========================================
# 1. 환경 변수 및 설정 (GitHub Secrets 연동)
# ==========================================

# GitHub Secrets에서 가져오기
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY")
SEARCH_ENGINE_ID = os.environ.get("SEARCH_ENGINE_ID")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD")

# 수신자 목록
def get_active_subscribers():
    print("📋 구독자 명단 확인 중...")
    
    # 1. GitHub Secrets에서 JSON 키 가져오기
    json_str = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    
    if not json_str:
        print("⚠️ 경고: GCP_SERVICE_ACCOUNT_JSON 시크릿이 없습니다.")
        return []

    try:
        # 2. 인증 및 시트 연결
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = json.loads(json_str) 
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        # 파일명 정확히 입력
        sheet = client.open("QuantLab Subscribers").sheet1
        data = sheet.get_all_records()
        
        active_emails = []
        today = datetime.now().strftime("%Y-%m-%d")

        for row in data:
            email = row.get('email')        
            end_date = row.get('end_date')
            canceled_at = row.get('canceled_at') 

            # 취소 날짜가 비어있는지 확인 (비어있으면 True)
            is_canceled = str(canceled_at).strip() != ""
            
            # 이메일 존재 + 만료 안 됨 + 취소 안 함
            if email and end_date and not is_canceled:
                if end_date >= today:
                    active_emails.append(email)
                else:
                    print(f"  🚫 만료된 구독자 제외: {email}")
            elif is_canceled:
                print(f"  👋 구독 취소자(발송 제외): {email}")
        
        print(f"✅ 활성 구독자 {len(active_emails)}명 추출 완료.")
        return active_emails

    except Exception as e:
        print(f"❌ 구글 시트 읽기 실패: {e}")
        return []

# -----------------------------------------------------------
# 수신자 목록 통합 (환경변수 + 구글시트)
# -----------------------------------------------------------
# 1. 환경변수(관리자) 이메일 처리
env_emails = os.environ.get("RECEIVER_EMAILS", "")
admin_list = [e.strip().lower() for e in env_emails.split(",") if e.strip()]

# 2. 구글 시트 구독자 이메일 처리
raw_subscribers = get_active_subscribers()
subscriber_list = [e.strip().lower() for e in raw_subscribers if e and e.strip()]

# 3. 합치기 및 중복 제거
unique_emails = set(admin_list + subscriber_list)

# 4. 최종 리스트 변환
RECEIVER_EMAILS = list(unique_emails)

print(f"📩 최종 발송 대상(중복 제거됨): {len(RECEIVER_EMAILS)}명")
# 디버깅용: 실제 리스트 확인 (로그에는 남지만 보안상 주의)

AVAILABLE_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-flash-lite",
]

# API 키 설정
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("❌ 경고: GEMINI_API_KEY가 없습니다.")

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
# 2. 기능 함수
# ==========================================

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def search_pdf_reports(keyword, sites):
    site_query = " OR ".join([f"site:{site}" for site in sites])
    # 검색 날짜 필터 (최근 3개월 등 유동적 조정 가능, 여기선 검색 API의 dateRestrict 사용)
    final_query = f"{keyword} filetype:pdf ({site_query})"
    print(f"🔎 검색 쿼리 생성 중... (타겟: {len(sites)}곳)")

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_SEARCH_API_KEY,
        'cx': SEARCH_ENGINE_ID,
        'q': final_query,
        'num': 10, # 검색 개수 조절
        'dateRestrict': 'w1' 
    }
    try:
        response = requests.get(url, params=params).json()
        pdf_links = []
        if 'items' in response:
            for item in response['items']:
                pdf_links.append({'title': item['title'], 'link': item['link']})
        return pdf_links
    except Exception as e:
        print(f"❌ 검색 에러: {e}")
        return []

def extract_text_fast(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://www.google.com/'
        }
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"   💨 패스 (접근 불가: {response.status_code})")
            return None

        if len(response.content) < 1000:
            print("   💨 패스 (파일 너무 작음)")
            return None

        f = io.BytesIO(response.content)
        reader = PdfReader(f)

        if reader.is_encrypted:
            print("   🔒 패스 (암호화됨)")
            return None

        text = ""
        # 앞 15페이지만 읽기 (토큰 절약 및 속도)
        pages_to_read = min(len(reader.pages), 15)
        for page_num in range(pages_to_read):
            extract = reader.pages[page_num].extract_text()
            if extract: text += extract
                
        if len(text.strip()) < 50:
            print("   ⚠️ 패스 (텍스트 추출 실패 - 스캔본 의심)")
            return None

        return text

    except requests.exceptions.Timeout:
        print("   ⏰ 패스 (15초 초과)")
        return None
    except Exception:
        print("   ❌ 패스 (다운로드 에러)")
        return None

def generate_with_rotation(prompt):
    start_time = time.time()
    print(f"      ▶️ AI 모델 호출 중...", flush=True)

    for i, model_name in enumerate(AVAILABLE_MODELS):
        try:
            print(f"      ⏳ [시도 {i+1}] {model_name}...", end=" ", flush=True)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            elapsed = time.time() - start_time
            print(f"✅ 성공 ({elapsed:.1f}초)", flush=True)
            return response.text, model_name
        except Exception as e:
            print(f"\n      ❌ 실패 ({model_name}): {e}", flush=True)
            time.sleep(1)
            continue

    return "분석 실패", "None"

# 웹사이트용 마크다운 저장 함수
def save_to_markdown(content,full_content):
    # 1. 폴더 생성 (data 폴더와 그 안에 archive 폴더까지)
    if not os.path.exists('data/archive'):
        os.makedirs('data/archive')
        
    # [저장 1] 메인 화면용 (항상 덮어씌움 -> 최신 유지)
    with open("data/daily_report.md", "w", encoding="utf-8") as f:
        f.write(content)
        
    # [저장 2] 기록 보관용 (날짜가 이름에 들어감 -> 안 지워짐)
    # 파일명 예시: data/archive/2025-12-19_report.md
    today_str = get_kst_now().strftime('%Y-%m-%d')
    archive_path = f"data/archive/{today_str}_report.md"
    
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(full_content)

    print(f"✅ 저장 완료: daily_report.md 및 {today_str}_report.md")

def send_email(subject, body):
    if not GMAIL_USER or not GMAIL_APP_PWD: 
        print("❌ 이메일 설정이 없어 전송을 건너뜁니다.")
        return
    if not RECEIVER_EMAILS: return

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(RECEIVER_EMAILS)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PWD)
        server.send_message(msg)
        server.quit()
        print(f"   📧 이메일 전송 완료 (총 {len(RECEIVER_EMAILS)}명)")
    except Exception as e:
        print(f"   ❌ 이메일 전송 실패: {e}")

# ==========================================
# 3. 메인 실행
# ==========================================
if __name__ == "__main__":
    print(f"🚀 '{SEARCH_KEYWORD}' 고속 분석 시작...\n")

    reports = search_pdf_reports(SEARCH_KEYWORD, TARGET_SITES)

    if not reports:
        print("❌ 검색 결과가 없습니다.")
        # 실패 시에도 빈 파일이라도 만들어야 에러 방지 가능
        save_to_markdown("오늘은 새로운 리포트가 검색되지 않았습니다.")
    else:
        success_count = 0
        collected_insights = []

        for i, report in enumerate(reports):
            print(f"\n[{i+1}/{len(reports)}] 확인 중: {report['title'][:30]}...")

            pdf_text = extract_text_fast(report['link'])

            if pdf_text and len(pdf_text) > 500:
                print("   📝 텍스트 확보! 분석 시작...")

                prompt = f"""당신은 월스트리트의 최상위 '글로벌 매크로 전략가'입니다.
주어진 리포트를 분석하여 핵심 인사이트를 추출하십시오. 또한 모든 대답은 한국어로 작성하십시오.

[보고서 정보]
제목: {report['title']}

[분석 지침]
1. 일반적인 내용은 제거하고, 구체적이고 날카로운 통찰 위주로 작성하십시오.
2. 모든 주장은 보고서 내의 '숫자'나 '사례'로 뒷받침되어야 합니다.

[출력 형식 (Markdown)]
### 1. 🚨 핵심 시장 변화
* (내용)

### 2. 🩸 고통과 기회
* (내용)

### 3. 📊 필수 데이터
* (내용)

### 4. 💰 유망 섹터
* (내용)

[텍스트]:
{pdf_text[:30000]}
"""
                insight, model_used = generate_with_rotation(prompt)

                summary = f"📄 **{report['title']}**\n🔗 {report['link']}\n{insight}\n"
                collected_insights.append(summary)
                success_count += 1

                time.sleep(2)
            else:
                pass

        if collected_insights:
            print(f"\n🎉 총 {success_count}건 성공! 종합 분석 중...")
            
            # 1. 개별 요약본들을 하나의 문자열로 합치기
            all_summaries_text = "\n\n---\n".join(collected_insights)
            
            # (프롬프트에는 요약본을 보여주기만 하고, 출력 포맷에는 포함하지 않음)
            final_prompt = f"""
당신은 수석 애널리스트입니다. 
아래 제공된 {success_count}개의 [개별 리포트 요약본]을 바탕으로 최종 결론을 도출하십시오.
모든 답변은 한국어로 작성하십시오.

[분석 지침]
1. 상호 검증: 여러 보고서의 공통된 합의(Consensus)를 찾으십시오.
2. 이견: 전망이 엇갈리는 부분은 리스크로 명시하십시오.
3. 큰 그림: 개별 사건들을 연결하여 거시적 인사이트를 제공하십시오.

[개별 리포트 요약본 데이터]:
{all_summaries_text}

[출력 형식 (Markdown)]
# 🌍 Global Market Synthesis Report ({get_kst_now().strftime('%Y-%m-%d')})

## 1. Executive Summary
* (핵심 메시지 한 문장)

## 2. Mega Trends
* (공통된 거대한 변화 3가지)

## 3. Alpha Opportunities (초과 수익 기회)
* (구체적 근거 포함)

## 4. Risk Assessment
* (하방 위험 요인)
"""
            # 2. AI에게 종합 분석
            final_insight, final_model = generate_with_rotation(final_prompt)
            
            footer = """
\n\n
--------------------------------------------------
* 본 메일은 Quant Lab 구독 서비스의 일환으로 발송되었습니다.
* 수신을 원치 않으시면 웹사이트의 [구독 취소] 탭을 이용해주세요.
--------------------------------------------------
"""
            
            # 3. AI의 종합 분석 뒤에 개별 리포트 요약을 수동으로 붙임
            final_report_content = f"{final_insight}\n\n---\n## 📚 Individual Report Summaries\n(아래 내용은 개별 리포트의 요약입니다)\n\n{all_summaries_text} {footer}"

            # 4. 저장 및 전송(웹사이트에는 최종 요약본만, 메일 및 DB에는 개별 리포트 포함)
            save_to_markdown(final_insight,final_report_content)
            send_email(f"[Quant-Lab] {SEARCH_KEYWORD} 종합 리포트", final_report_content)
            
            print("\n✅ 모든 작업 완료!")
            
        else:
            print("\n❌ 분석 성공한 리포트가 없습니다.")
            save_to_markdown("분석 가능한 리포트를 찾지 못했습니다.")
