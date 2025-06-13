# NutChat 실행 방법

1. 환경 준비
   1. Python 설치<br>
        Python 3.8 이상이 설치되어 있어야 함함.<br>
        (명령 프롬프트에서 `python --version`으로 확인)
   2. 필수 라이브러리 설치<br>
   `pip install flask flask-cors pandas openpyxl google-generativeai`

2. 데이터파일 준비<br>
    `nutrition.xlsx`파일을 `app.py`와 같은 폴더 내에 위치

3. API 키 설정<br>
    `app.py` 내 `GOOGLE_API_KEY` 변수에 본인의 Google Gemini API 키를 입력

4. 서버 실행<br>
    명령 프롬프트(터미널)에서 프로젝트 폴더로 이동 후에 아래 명령어 실행:<br>
    ```Bash
    python app.py
    ```
    정상적으로 실행되면 `http://0.0.0.0:5000` 또는 `http://localhost:5000`에서 서버가 동작

5. 프론트엔드 실행 - `index.html` 파일


# NutChat 사용방법
1. 입력칸에 음식과 수량을 입력
2. 서버가 영양소를 계산해 결과와 식단 조언을 반환
3. 후보가 여러 개인 경우, 프론트엔드에서 직접 선택 후 결과를 받을 수 있음

참고:
* `nutrition.xlsx`이 없거나 API 키가 잘못되면 실행이 중단될 수 있음
