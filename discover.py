name: Weekly Repo Discovery

on:
  schedule:
    - cron: '0 0 * * 0'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  discover-new-repos:
    runs-on: ubuntu-latest
    # 添加环境变量，强制 Actions 启用最新的 Node.js 24 以消除弃用警告
    env:
      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python 3.10
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Run Discovery Script in Virtual Environment
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # 建立并激活虚拟环境
          python -m venv venv
          source venv/bin/activate
          # 安装基础请求库
          pip install --upgrade pip
          pip install requests
          # 执行自动发现脚本
          python discover.py

      - name: Commit and push changes
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "Auto-discover and update repo lists & stats"
          file_pattern: "*.txt *.json"
