#!/usr/bin/env bash
# 의존성 없이 전체 테스트 + 스모크 실행
set -euo pipefail
cd "$(dirname "$0")"
echo "== unit tests =="
python3 -m unittest discover -s tests -t . -q
echo
echo "== CLI 스모크 =="
for c in check policy-check calendar budget buckets triggers; do
  printf '  %-14s ' "$c"
  python3 -m fde "$c" >/dev/null && echo ok
done
printf '  %-14s ' "decide --quick"
python3 -m fde decide --quick >/dev/null && echo ok
printf '  %-14s ' "sensitivity"
python3 -m fde sensitivity >/dev/null && echo ok
printf '  %-14s ' "risk"
python3 -m fde risk --paths 50 >/dev/null && echo ok
printf '  %-14s ' "backtest"
python3 -m fde backtest --dates 2026-06-01,2026-09-05 >/dev/null && echo ok
echo
echo "전부 통과."
