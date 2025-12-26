import pandas as pd
import os

# 1. 파일 이름 설정
input_file = 'C:\Y\Study\Projects\StockAnalysis\data\exchange_rates.csv'         # 원본 파일명
output_file = 'C:\Y\Study\Projects\StockAnalysis\data\exchange_rates_filled.csv' # 저장할 파일명

def fill_missing_dates():
    # 파일이 있는지 확인
    if not os.path.exists(input_file):
        print(f"❌ 오류: '{input_file}' 파일을 찾을 수 없습니다.")
        return

    print("🔄 데이터 처리 중...")

    # 2. CSV 읽기
    df = pd.read_csv(input_file)

    # 3. 전처리: 날짜 형식으로 변환 후 인덱스로 설정
    # (엑셀 등에서 포맷이 꼬였을 수 있으니 to_datetime으로 통일)
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)

    # 4. 빈 날짜 생성 로직
    # 데이터의 시작일(min)부터 종료일(max)까지 하루도 빠짐없는 날짜 범위 생성
    full_date_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')

    # 기존 데이터에 빈 날짜 범위를 덮어씌움 (없는 날짜는 NaN으로 생김)
    df_filled = df.reindex(full_date_range)

    # 5. 결측치 채우기 (핵심!)
    # ffill() = Forward Fill: NaN을 만나면 '직전 유효 값'을 복사해서 채움
    df_filled['USD_KRW'] = df_filled['USD_KRW'].ffill()

    # 6. 마무리 및 저장
    df_filled.reset_index(inplace=True)               # 인덱스를 다시 컬럼으로
    df_filled.rename(columns={'index': 'Date'}, inplace=True) # 컬럼명 복구
    df_filled['Date'] = df_filled['Date'].dt.strftime('%Y-%m-%d') # YYYY-MM-DD 포맷 유지

    # CSV 저장
    df_filled.to_csv(output_file, index=False)

    print(f"✅ 완료! '{output_file}' 파일이 생성되었습니다.")
    print(f"📊 처리 전: {len(df)}행 -> 처리 후: {len(df_filled)}행")

if __name__ == "__main__":
    fill_missing_dates()