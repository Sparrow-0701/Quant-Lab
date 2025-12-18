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
emails_env = os.environ.get("RECEIVER_EMAILS", "")
if emails_env:
    # 쉼표(,) 기준으로 자르고, 혹시 모를 공백(띄어쓰기) 제거
    RECEIVER_EMAILS = [e.strip() for e in emails_env.split(",") if e.strip()]
else:
    print("⚠️ 경고: 수신자 이메일 설정이 없습니다.")
    RECEIVER_EMAILS = [] # 빈 리스트

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
    "blackrock.com", "macquarie.com", "kkr.com", 
    "goldmansachs.com", "jpmorgan.com", "morganstanley.com", 
    "mckinsey.com", "pwc.com", 
    "worldbank.org", "adb.org"
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

# [추가됨] 웹사이트용 마크다운 저장 함수
def save_to_markdown(content):
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
        f.write(content)

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
{pdf_text[:20000]}
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
            
            # --- [핵심] 최종 종합 리포트 생성 ---
            final_prompt = f"""
당신은 수석 애널리스트입니다. 
아래 {success_count}개의 개별 리포트 요약본들을 통합 분석하여 최종 결론을 도출하십시오. 또한 모든 대답은 한국어로 작성하십시오.

[분석 지침]
1. 상호 검증: 여러 보고서의 공통된 합의(Consensus)를 찾으십시오.
2. 이견: 전망이 엇갈리는 부분은 리스크로 명시하십시오.
3. 큰 그림: 개별 사건들을 연결하여 거시적 인사이트를 제공하십시오.

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

---
## 📚 Individual Report Summaries
(아래 내용은 개별 리포트의 요약입니다)

{"".join(collected_insights)}
"""
            final_insight, final_model = generate_with_rotation(final_prompt)
            
            final_report_content = final_insight # 웹사이트 및 메일 본문용

            # 1. 웹사이트용 파일 저장
            save_to_markdown(final_report_content)

            # 2. 이메일 전송
            send_email(f"[Quant-Lab] {SEARCH_KEYWORD} 종합 리포트", final_report_content)
            
            print("\n✅ 모든 작업 완료!")
            
        else:
            print("\n❌ 분석 성공한 리포트가 없습니다.")
            save_to_markdown("분석 가능한 리포트를 찾지 못했습니다.")
