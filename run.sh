#!/bin/bash
# 대시보드 실행. PC는 http://localhost:8501, 핸드폰은 같은 와이파이에서 http://<PC IP>:8501 로 연다.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/streamlit run app.py --server.address 0.0.0.0 --server.port 8501
