# 미국주식 대시보드

티커나 회사명(테슬라, tesla, TSLA)을 넣으면 종목정보, 시황, 관련 뉴스, MDD를 보여주는 Streamlit 앱.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

데이터는 Yahoo Finance, Google News, 네이버 증권 자동완성에서 가져온다. 투자 판단의 참고 자료로만 쓴다.
