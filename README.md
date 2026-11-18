# 미국주식 대시보드

티커나 회사명(테슬라, tesla, TSLA)을 넣으면 종목정보, 시황, 관련 뉴스, MDD를 보여주는 Streamlit 앱.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

데이터는 Yahoo Finance, Google News, 네이버 증권 자동완성에서 가져온다. 투자 판단의 참고 자료로만 쓴다.

## 매매 신호 (GitHub 페이지 `#signals`)

`signals.py` 가 보유 종목(HOLDINGS)마다 RSI·이동평균·볼린저밴드·ATR로 매수 우위/관망/매도 우위와 분할 매수·익절·손절 가격대를 계산한다. 하루 종가 기준 참고용이며 실제 주문은 하지 않는다. 평단·수량은 브라우저(localStorage)에만 저장한다.
