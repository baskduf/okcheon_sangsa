# myapp/views.py
import zipfile
import os
from django.conf import settings
from django.shortcuts import render, redirect
from .forms import UploadZipFileForm
from .models import UploadedZipFile
import locale
import re
import datetime
import google.generativeai as genai
import markdown
from django.http import JsonResponse
from dotenv import load_dotenv
import json


locale.setlocale(locale.LC_TIME, 'ko_KR.UTF-8')


def upload_zip_file(request):
    error_msg =""
    if request.method == 'POST' and request.FILES['zip_file']:
        form = UploadZipFileForm(request.POST, request.FILES)
        if form.is_valid():
            zip_file_instance = form.save()  # 업로드된 ZIP 파일을 저장
            zip_file_path = zip_file_instance.zip_file.path  # 파일 경로
            output_dir = os.path.join(settings.MEDIA_ROOT, 'extracted_files', str(zip_file_instance.id))
            # 압축 풀기
            try:
                recent_chat = extract_recent_7_days_chat(zip_file_path, output_dir)
                print(recent_chat)
                # .env 파일 경로 설정
                # 프로젝트 최상단 경로 동적으로 계산
                dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
                # .env 파일 로드
                load_dotenv(dotenv_path=dotenv_path)
                # 환경 변수에서 API 키 가져오기

                API_KEY = os.getenv("API_KEY")
                if not API_KEY:
                    raise ValueError("API_KEY is not set in the environment variables.")

                import openai

                # OpenAI API 키 설정
                openai.api_key = API_KEY

                #print(recent_chat)
                sys_prompt = """
# Role: 근무 스케줄 분석 전문가

당신은 근무 스케줄 분석 전문가입니다. 다음은 근무 스케줄 조정을 위해 수집된 카카오톡 단체 채팅방 대화 내용입니다.

## Goal
1. 주어진 대화 전체(시간순)에 나타난 직원별 근무 가능 요일을 분석한다.
2. 근무 시간대는 "open"(오픈조, 오전 6시~12시), "close"(마감조, 12시~마감), "unavailable"(불가능) 세 가지로 구분한다.
3. **만약 대화에 구체적으로 open/close(오전/오후)로 나뉜 언급이 전혀 없을 경우**, 해당 요일은 “오전부터 마감까지 모두 가능”이라고 간주한다. 즉, 그 요일을 open과 close에 모두 넣는다.
4. 가장 최근(가장 나중)에 언급된 변동사항이 이전 메시지와 충돌하면, 최신 정보를 최우선으로 반영한다.
5. 근무자는 최원빈,오태균,임상훈,김태호,최준,태광 만 있다.

## 출력 형식 (Output Format)
- 결과는 다음 JSON 형태로 출력한다:


```
json |{ "직원이름": { "open": ["월", "화"], "close": ["수", "목"], "unavailable": ["금", "토", "일"] }, ... }
```


### 상세 규칙
1. **요일 표기**: 월, 화, 수, 목, 금, 토, 일
2. 한 요일이 open과 close 모두 가능할 수도 있음 (풀타임 가능).
3. “완전 불가능”, “가족 행사로 절대 안됨” 등은 **unavailable**에 반드시 포함.
4. **조건부 가능**(“급하면 가능” 등)은, 명확히 가능이 확정된 게 아니므로 unavailable로 처리.
5. 대화 중 **open**(오전 가능) 또는 **close**(오후 가능)로 나뉘어 언급되지 않았으면, **그 요일은 open과 close 둘 다 가능**하다고 해석(= 풀타임 가능).
6. 대화 중 “월, 화, 수, 일 빼고 가능”은 남은 요일 “목, 금, 토 open과 close 둘 다 가능”하다고 해석
7. 가장 최근 메시지를 우선 적용하여, 이전 메시지와 충돌되면 최신 정보를 반영.
8. 최종적으로 JSON 포맷에 맞춰서 `{ "직원이름": {...} }` 구조로만 답을 제시한다.

## Chain-of-Thought (COT) Process
1. 대화를 **시간순**으로 살펴, 각 직원의 요일별 언급을 정리한다.
2. 메시지에 명시적으로 “오전/오픈”, “오후/마감”이 언급된 경우 해당 시간대만 가능으로 등록한다.
3. 메시지에서 시간대 구분 없이 "월요일 가능"이라고만 적혔다면, 해당 요일은 open과 close를 모두 가능으로 설정한다.
4. 이전 메시지와 충돌하는 내용이 가장 최근 메시지에 있다면, 최신 정보를 우선한다.
5. 최종적으로 JSON 형태의 결과만 출력한다.

            """

                # GPT 호출
                result = openai.ChatCompletion.create(
                    model="gpt-4o",  # 또는 "gpt-3.5-turbo"
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": recent_chat}
                    ]
                )
                # 응답 출력
                result_text = result['choices'][0]['message']['content']
                # 줄바꿈 문자(\n) 제거
                clean_result_text = clean_json_text(result_text)
                try:
                    data = json.loads(clean_result_text)
                    scheduler = oc_scheduler(data)
                    return render(request, 'schedule.html', {"schedule":scheduler, "data": data, "error" : error_msg})
                except json.JSONDecodeError as e:
                    error_msg = f"오류가 발생했습니다. 분석할 충분한 데이터가 제공되지 않았습니다. {e}"
            except Exception as e:
                error_msg = f"오류가 발생했습니다. 분석할 충분한 데이터가 제공되지 않았습니다. {e}"
    else:
        form = UploadZipFileForm()
    
    return render(request, 'upload_zip_file.html', {'form': form, 'error' : error_msg})

def clean_json_text(raw_text):
    # 텍스트에서 불필요한 공백과 줄바꿈 제거
    cleaned_text = re.sub(r'\s+', ' ', raw_text)  # 여러 공백을 하나로
    cleaned_text = cleaned_text.strip()  # 양쪽 공백 제거
    cleaned_text = cleaned_text.replace('```json', '')  # json 시작 부분 제거
    cleaned_text = cleaned_text.replace('```', '')  # 끝 부분 제거
    return cleaned_text

def extract_recent_7_days_chat(zip_file_path, output_dir):
    # Step 0: 압축 파일 존재 여부 확인
    if not os.path.exists(zip_file_path):
        raise FileNotFoundError(f"압축 파일이 존재하지 않습니다: {zip_file_path}")
    print(f"압축 파일이 확인되었습니다: {zip_file_path}")

    # Step 1: 압축 해제
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
        zip_ref.extractall(output_dir)

    print(f"압축 해제 완료. 파일이 저장된 디렉토리: {output_dir}")

    # Step 2: txt 파일 찾기
    txt_file_path = None
    for root, dirs, files in os.walk(output_dir):
        for file in files:
            if file.endswith('.txt'):
                txt_file_path = os.path.join(root, file)
                break
        if txt_file_path:
            break

    if not txt_file_path:
        # 압축 해제 디렉토리 삭제
        for root, dirs, files in os.walk(output_dir, topdown=False):
            for file in files:
                os.remove(os.path.join(root, file))
            for dir in dirs:
                os.rmdir(os.path.join(root, dir))
        os.rmdir(output_dir)
        raise FileNotFoundError("txt 파일을 찾을 수 없습니다.")
    
    print(f"대화 txt 파일이 확인되었습니다: {txt_file_path}")
    
    #파싱 로직
    parsed_chat = parse_chat_log(txt_file_path)

    # Step 4: txt 파일과 압축 해제된 파일 삭제
    os.remove(txt_file_path)
    for root, dirs, files in os.walk(output_dir, topdown=False):
        for file in files:
            os.remove(os.path.join(root, file))
        for dir in dirs:
            os.rmdir(os.path.join(root, dir))
    os.rmdir(output_dir)
    # Step 5: 결과 반환 (최근 7일 대화 내용만)
    return parsed_chat

from datetime import datetime, timedelta

def parse_chat_log(txt_file_path):
    # 현재 날짜 설정 (2024년 12월 27일)
    current_date = datetime.now()
    # 4일 전 날짜 계산
    four_days_ago = current_date - timedelta(days=3)
    
    # 결과를 저장할 딕셔너리
    chat_by_date = {}
    current_chat_date = None
    
    # 날짜를 datetime으로 변환하는 함수
    def convert_to_datetime(date_str):
        # "2024년 12월 27일 금요일" 형식 변환
        match = re.match(r'(\d{4})년 (\d{1,2})월 (\d{1,2})일', date_str)
        if match:
            year, month, day = map(int, match.groups())
            return datetime(year, month, day)
        return None

    try:
        with open(txt_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 날짜 행인지 확인
            if '년' in line and '월' in line and '일' in line and '요일' in line:
                date_obj = convert_to_datetime(line)
                if date_obj and four_days_ago <= date_obj <= current_date:
                    current_chat_date = line
                    if current_chat_date not in chat_by_date:
                        chat_by_date[current_chat_date] = []
                continue
            
            # 현재 날짜가 최근 4일 이내인 경우에만 메시지 추가
            if current_chat_date:
                chat_by_date[current_chat_date].append(line)
    
        # 날짜 오름차순 정렬
        sorted_dates = sorted(list(chat_by_date.keys()), 
                            key=lambda x: convert_to_datetime(x))
        
        # 결과를 하나의 문자열로 합치기
        result = ""
        for date in sorted_dates:
            result += f"=== {date} ===\n"
            result += "\n".join(chat_by_date[date]) + "\n"
        
        return result.strip()
    
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return None


def format_chat_content(filtered_chat):
    formatted_output = ""
    for date, messages in filtered_chat.items():
        formatted_output += f"\n=== {date} ===\n"
        for msg in messages:
            formatted_output += f"{msg}\n"
    return formatted_output.strip()

def oc_scheduler(data):
    import random
    # 요일 초기화
    days_of_week = ["월", "화", "수", "목", "금", "토", "일"]
    schedule = {day: {"open": None, "close": None} for day in days_of_week}
    
    # 각 직원의 배정 횟수를 기록 (open과 close 각각 추적)
    assignments = {employee: {"open": 0, "close": 0, "total": 0} for employee in data.keys()}
    
    # 각 직원별 가능한 총 시프트 수 계산
    availability_count = {
        employee: {
            "open": len(availability["open"]),
            "close": len(availability["close"]),
            "total": len(availability["open"]) + len(availability["close"])
        }
        for employee, availability in data.items()
    }
    
    # 목표 배정 횟수 계산 (공평한 분배를 위해)
    total_shifts = len(days_of_week) * 2  # open과 close 각각
    target_shifts_per_person = total_shifts / len(data)
    
    def get_best_candidate(candidates, shift_type):
        if not candidates:
            return None
        # 1. 현재까지 총 배정 횟수가 가장 적은 사람
        # 2. 특정 시프트(open/close) 배정 횟수가 적은 사람
        # 3. 가능한 시프트 수가 적은 사람 (즉, 제약이 많은 사람)
        return min(candidates, key=lambda x: (
            assignments[x]["total"],
            assignments[x][shift_type],
            -availability_count[x][shift_type]  # 음수로 변환하여 가능한 시프트가 적은 사람 우선
        ))
    
    # 1. 우선 모든 직원이 최소 1회씩 배정되도록 함
    for employee in data.keys():
        if assignments[employee]["total"] == 0:
            # open 시도
            for day in days_of_week:
                if schedule[day]["open"] is None and day in data[employee]["open"]:
                    schedule[day]["open"] = employee
                    assignments[employee]["open"] += 1
                    assignments[employee]["total"] += 1
                    break
            # close 시도
            if assignments[employee]["total"] == 0:  # open 배정 실패한 경우
                for day in days_of_week:
                    if schedule[day]["close"] is None and day in data[employee]["close"]:
                        schedule[day]["close"] = employee
                        assignments[employee]["close"] += 1
                        assignments[employee]["total"] += 1
                        break
    
    # 2. 나머지 시프트 배정
    for day in days_of_week:
        for shift_type in ["open", "close"]:
            if schedule[day][shift_type] is None:
                candidates = [
                    employee for employee in data.keys()
                    if day in data[employee][shift_type] and
                    assignments[employee]["total"] < target_shifts_per_person * 1.5  # 특정 직원에게 과도한 배정 방지
                ]
                
                selected = get_best_candidate(candidates, shift_type)
                
                # 만약 조건이 너무 엄격해서 후보가 없다면, 조건을 완화
                if selected is None:
                    candidates = [
                        employee for employee in data.keys()
                        if day in data[employee][shift_type]
                    ]
                    selected = get_best_candidate(candidates, shift_type)
                
                if selected:
                    schedule[day][shift_type] = selected
                    assignments[selected][shift_type] += 1
                    assignments[selected]["total"] += 1
    
    # 3. 비어 있는 슬롯 확인 및 필수 배정
    for day in days_of_week:
        for shift_type in ["open", "close"]:
            if schedule[day][shift_type] is None:
                # 가능한 모든 직원 중에서 배정
                candidates = [
                    employee for employee in data.keys()
                    if day in data[employee][shift_type]
                ]
                if not candidates:
                    # 그래도 후보가 없으면 강제로 아무나 배정
                    candidates = list(data.keys())
                
                # 가장 적게 배정된 직원 선택
                selected = min(candidates, key=lambda x: assignments[x]["total"])
                
                schedule[day][shift_type] = selected
                assignments[selected][shift_type] += 1
                assignments[selected]["total"] += 1
    
    return schedule
