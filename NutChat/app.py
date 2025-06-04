# app.py
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
import re
import os
import sys
import json

app = Flask(__name__)
CORS(app)

# --- nutrition.xlsx 파일 로드 ---
try:
    # header=1: 엑셀의 2번째 행(인덱스 1)을 컬럼명으로 사용
    # skiprows=[2]: 엑셀의 3번째 행(인덱스 2, 단위 행)을 건너뜀
    df_nutrition = pd.read_excel('nutrition.xlsx', sheet_name=0, header=0, skiprows=[1])
    print("nutrition.xlsx 파일을 성공적으로 로드했습니다.")

    # 모든 컬럼명에서 앞뒤 공백 제거 (매우 중요!)
    df_nutrition.columns = df_nutrition.columns.str.strip()

    # '식품명' 컬럼을 문자열로 변환
    if '식품명' in df_nutrition.columns:
        df_nutrition['식품명'] = df_nutrition['식품명'].astype(str)
    else:
        print("경고: '식품명' 컬럼을 찾을 수 없습니다. 음식 검색 기능에 문제가 발생할 수 있습니다.")

    # 계산에 사용되는 주요 숫자형 열들을 명시적으로 float 타입으로 변환
    numeric_cols_refined = [
        '에너지', '단백질', '지방', '탄수화물', '당류', '총 식이섬유',
        '나트륨', '비타민 A', '비타민 B12', '비타민 C', '비타민 D', '비타민 E',
        '총 지방산', '총 필수 지방산', '총 포화 지방산',
        '총 불포화 지방산', '총 트랜스 지방산',
        '식염상당량', '폐기율'
    ]

    for col in numeric_cols_refined:
        if col in df_nutrition.columns:
            df_nutrition[col] = pd.to_numeric(df_nutrition[col], errors='coerce').fillna(0)
        else:
            print(f"경고: XLSX 파일에 '{col}' 열이 존재하지 않습니다. 해당 열은 변환되지 않습니다. (이름 확인 필요)")

except FileNotFoundError:
    print("오류: 'nutrition.xlsx' 파일을 찾을 수 없습니다. 'app.py'와 같은 디렉터리에 파일을 놓아주세요.")
    sys.exit(1)
except Exception as e:
    print(f"XLSX 파일 로드 중 예상치 못한 오류 발생: {e}")
    sys.exit(1)

# Gemini API 설정
GOOGLE_API_KEY = ""  # 여기에 발급받은 실제 Gemini API 키를 붙여넣으세요!
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# 한 끼 권장 영양 섭취량 (성인 평균 기준, 예시)
RDA_PER_MEAL = {
    '에너지': 700,
    '탄수화물': 45,
    '단백질': 20,
    '지방': 15,
    '당류': 16,
    '총 식이섬유': 8,
    '총 포화 지방산': 5,
    '총 트랜스 지방산': 0.8
}


# --- 헬퍼 함수 ---
def search_food_in_db(food_name):
    cleaned_food_name = food_name.strip()
    # 완전 일치
    exact_matches = df_nutrition[df_nutrition['식품명'].str.strip() == cleaned_food_name]
    if not exact_matches.empty:
        return exact_matches.iloc[0].to_dict(), "exact_match", None
    # 부분 일치
    partial_matches = df_nutrition[df_nutrition['식품명'].str.contains(cleaned_food_name, na=False, case=False)]
    if not partial_matches.empty:
        # 후보 리스트 반환
        candidates = partial_matches['식품명'].tolist()
        return None, "multiple_candidates", candidates
    return None, "no_match", None


def calculate_nutrients(food_data_list):
    total_nutrients = {
        '에너지': 0.0,
        '탄수화물': 0.0,
        '단백질': 0.0,
        '지방': 0.0,
        '당류': 0.0,
        '총 식이섬유': 0.0,
        '총 포화 지방산': 0.0,
        '총 트랜스 지방산': 0.0
    }

    for item_data in food_data_list:
        food_name = item_data['name']
        # Gemini가 변환해준 quantity_g를 직접 사용
        # 만약 quantity_g가 없거나 유효하지 않으면 기본값 100g 사용
        quantity_g = item_data.get('quantity_g')
        if not isinstance(quantity_g, (int, float)) or quantity_g <= 0:
            print(f"경고: '{food_name}'에 대한 유효한 'quantity_g' 정보가 없습니다. 기본값 100g을 사용합니다.")
            quantity_g = 100.0

        food_info = None
        food_info_dict, match_type, _ = search_food_in_db(food_name)

        if match_type == "exact_match":
            food_info = food_info_dict

            # 여기서부터는 식품중량이나 기준량 컬럼을 사용하지 않습니다.
            # 데이터베이스의 영양성분은 100g 기준이라고 가정하고,
            # Gemini가 추정한 quantity_g에 비례하여 계산합니다.

            # DB 데이터가 100g 기준이라는 가정이므로, ratio는 quantity_g / 100.0 이 됩니다.
            ratio = quantity_g / 100.0

            for nutrient in total_nutrients.keys():
                if nutrient in food_info and pd.notna(food_info[nutrient]):
                    nutrient_value = food_info[nutrient] * ratio
                    total_nutrients[nutrient] += nutrient_value
                    

        else:  # no_match
            print(f"경고: '{food_name}'에 대한 영양 정보를 찾을 수 없습니다. 이 음식은 계산에서 제외됩니다.")
            continue

    return total_nutrients


def get_dietary_advice(consumed_nutrients, rda_nutrients):
    """
    Gemini API를 사용하여 식단 조언을 생성합니다.
    """
    prompt_parts = [
        "당신은 영양사 챗봇입니다. 사용자가 섭취한 음식의 영양성분과 권장 섭취량을 비교하여 구체적인 식단 조언을 해주세요.",
        "다음은 사용자가 섭취한 음식의 영양성분입니다:",
        f"**칼로리**: {consumed_nutrients['에너지']:.1f} kcal",
        f"**탄수화물**: {consumed_nutrients['탄수화물']:.1f} g",
        f"**단백질**: {consumed_nutrients['단백질']:.1f} g",
        f"**지방**: {consumed_nutrients['지방']:.1f} g",
        f"**당류**: {consumed_nutrients['당류']:.1f} g",
        f"**식이섬유**: {consumed_nutrients['총 식이섬유']:.1f} g",
        f"**포화지방산**: {consumed_nutrients['총 포화 지방산']:.1f} g",
        f"**트랜스지방산**: {consumed_nutrients['총 트랜스 지방산']:.1f} g",
        "",
        "다음은 한 끼 권장 영양 섭취량입니다:",
        f"권장 칼로리: {rda_nutrients['에너지']} kcal",
        f"권장 탄수화물: {rda_nutrients['탄수화물']} g",
        f"권장 단백질: {rda_nutrients['단백질']} g",
        f"권장 지방: {rda_nutrients['지방']} g",
        f"권장 식이섬유: {rda_nutrients['총 식이섬유']} g",
        f"권장 당류: {rda_nutrients['당류']} g 이하",
        f"권장 포화지방산: {rda_nutrients['총 포화 지방산']} g 이하",
        f"권장 트랜스지방산: {rda_nutrients['총 트랜스 지방산']} g 이하",
        "",
        "위 정보를 바탕으로 아래 항목에 대해 답변해 주세요:",
        "1. 부족한 영양소와 과다한 영양소를 각각 구체적으로 알려주세요.",
        "2. 부족한 영양소를 보충할 수 있는 음식 예시를 2가지 이상 제안해 주세요.",
        "3. 과다한 영양소를 줄이기 위한 식습관 또는 음식 선택 팁을 알려주세요.",
        "4. 전체 식단에 대한 간단한 종합 평가와 개선 방향을 제시해 주세요."
    ]

    try:
        response = model.generate_content(prompt_parts)
        return response.text
    except Exception as e:
        print(f"Gemini API 호출 중 오류 발생: {e}")
        return "죄송합니다. 식단 조언을 생성하는 중 오류가 발생했습니다."


def gemini_parse_food_input(input_text):
    prompt = f"""
    당신은 사용자로부터 섭취한 음식을 입력받아 JSON 형태로 파싱하는 도우미입니다.
    사용자 문장에서 음식명, 수량, 단위를 추출하고, 각 음식이 일반적으로 몇 그램(g)일지 **추정하여 'quantity_g' 필드에 숫자로 추가**하여 JSON 배열 형태로 반환해 주세요.

    규칙:
    1. 각 음식은 하나의 JSON 객체로 표현합니다: `{{'name': '음식명', 'quantity': 숫자, 'unit': '단위', 'quantity_g': 'g 단위로 변환된 예상 무게 (숫자)'}}`
    2. 'quantity_g'는 'quantity'와 'unit'을 바탕으로 해당 음식이 일반적으로 몇 그램(g)일지 합리적으로 추정하여 숫자로 기입합니다.
    3. 만약 'quantity'와 'unit'이 이미 그램(g) 단위라면, 'quantity_g'는 그 'quantity' 값을 그대로 사용합니다.
    4. '개', '컵', '그릇', '봉지' 등 비-g 단위의 경우, 일반적인 크기와 무게를 고려하여 'quantity_g'를 추정합니다.
       - 예시: 사과 1개 -> quantity_g: 200 (g)
       - 예시: 쌀밥 1공기 -> quantity_g: 210 (g)
       - 예시: 계란 후라이 1개 -> quantity_g: 60 (g)
       - 예시: 바나나 1개 -> quantity_g: 120 (g)
       - 예시: 배 1개 -> quantity_g: 500 (g)
       - 예시: 식빵 1조각 -> quantity_g: 30 (g)
    5. 수량이 명시되지 않으면 'quantity'는 기본값으로 100을 사용하고 'unit'은 'g'으로 가정하며, 'quantity_g'도 100으로 설정합니다.
    6. 다른 불필요한 설명 없이 오직 JSON 배열만 반환합니다.

    예시:
    - 사용자 입력: "사과 100g, 바나나 1개"
    - 출력:
    ```json
    [
      {{
        "name": "사과",
        "quantity": 100,
        "unit": "g",
        "quantity_g": 100
      }},
      {{
        "name": "바나나",
        "quantity": 1,
        "unit": "개",
        "quantity_g": 120
      }}
    ]
    ```
    - 사용자 입력: "점심으로 쌀밥 200g이랑 김치찌개 한그릇 먹었어."
    - 출력:
    ```json
    [
      {{
        "name": "쌀밥",
        "quantity": 200,
        "unit": "g",
        "quantity_g": 200
      }},
      {{
        "name": "김치찌개",
        "quantity": 1,
        "unit": "그릇",
        "quantity_g": 400
      }}
    ]
    ```
    - 사용자 입력: "계란 후라이"
    - 출력:
    ```json
    [
      {{
        "name": "계란 후라이",
        "quantity": 100,
        "unit": "g",
        "quantity_g": 100
      }}
    ]
    ```

    문장: "{input_text}"
    """
    try:
        response = model.generate_content(prompt)
        text_response = response.text.strip()

        if text_response.startswith('```json') and text_response.endswith('```'):
            json_str = text_response[7:-3].strip()
        else:
            json_str = text_response

        parsed_data = json.loads(json_str)
        return parsed_data
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 오류: {e}")
        print(f"Gemini 응답 내용 (파싱 실패): {text_response}")
        return None
    except Exception as e:
        print(f"Gemini API 호출 또는 파싱 중 예상치 못한 오류: {e}")
        print(f"Gemini 응답 내용 (오류 발생 시): {response.text if 'response' in locals() else '응답 없음'}")
        return None


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json

    # 1. 여러 음식 후보가 모두 선택된 경우
    if 'selected_foods' in data:
        food_items_to_process = data['selected_foods']
        # food_items_to_process: [{name: '선택된 식품명', quantity_g: ...}, ...]
        # DB에서 정확한 식품명으로 영양정보 찾기
        foods_for_calc = []
        for item in food_items_to_process:
            food_info_dict, match_type, _ = search_food_in_db(item['name'])
            if match_type == "exact_match":
                foods_for_calc.append({
                    "name": item['name'],
                    "quantity_g": item.get('quantity_g', 100),
                    "selected_food_code": food_info_dict.get('식품코드')
                })
        if not foods_for_calc:
            return jsonify({"error": "계산할 음식이 없습니다."}), 400
        calculated_nutrition = calculate_nutrients(foods_for_calc)
        dietary_advice = get_dietary_advice(calculated_nutrition, RDA_PER_MEAL)
        return jsonify({
            "calculated_nutrition": calculated_nutrition,
            "dietary_advice": dietary_advice
        })

    # 2. 일반 메시지 처리 (후보 선택 필요)
    user_message = data.get('message', '')
    if not user_message:
        return jsonify({"error": "메시지를 입력해주세요."}), 400

    food_items_to_process = []
    candidates_to_select = []

    parsed_food_list = gemini_parse_food_input(user_message)

    if not parsed_food_list:
        print(f"경고: Gemini 파싱 결과가 유효하지 않음: {parsed_food_list}")
        return jsonify({"error": "죄송합니다. 입력하신 음식 정보를 이해하기 어렵습니다. 다시 시도해 주세요."}), 400


    for item in parsed_food_list:
        food_name = item.get('name')
        if not food_name:
            continue
        food_info_dict, match_type, candidates = search_food_in_db(food_name)
        if match_type == "exact_match":
            item['selected_food_code'] = food_info_dict.get('식품코드')
            food_items_to_process.append(item)
        elif match_type == "multiple_candidates":
            candidates_to_select.append({
                "food_name": food_name,
                "candidates": candidates
            })
        else:
            # 후보가 없으면 food_name만 후보로 넣기
            candidates_to_select.append({
                "food_name": food_name,
                "candidates": [food_name]
            })

    # 후보가 하나라도 있으면, 후보 목록과 파싱된 음식 목록을 같이 반환
    if candidates_to_select:
        return jsonify({
            "select_candidates": candidates_to_select,
            "parsed_food_list": parsed_food_list
        }), 200

    # 후보가 모두 exact_match면 바로 계산
    if not food_items_to_process:
        return jsonify({"error": "계산할 음식을 찾을 수 없거나 유효하지 않습니다."}), 400

    calculated_nutrition = calculate_nutrients(food_items_to_process)
    dietary_advice = get_dietary_advice(calculated_nutrition, RDA_PER_MEAL)

    return jsonify({
        "calculated_nutrition": calculated_nutrition,
        "dietary_advice": dietary_advice
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)