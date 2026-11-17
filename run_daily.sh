#!/bin/sh
# Daily runner for cron. Edit the two paths below, then: chmod +x run_daily.sh
cd /path/to/nifty_mood || exit 1
# export ANTHROPIC_API_KEY="sk-ant-..."   # optional: AI explanations
/path/to/nifty_mood/.venv/bin/python mood_pipeline.py >> logs/mood_$(date +%Y%m%d).log 2>&1
