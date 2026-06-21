@echo off
REM 現場写真 PCサーバー 起動スクリプト（Windows）
REM 初回のみ依存関係をインストールします。

cd /d "%~dp0"

REM 仮想環境（無ければ作成）
if not exist ".venv\" (
    echo [setup] Python仮想環境を作成します...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo [setup] 依存パッケージをインストールします...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

echo [run] サーバーを起動します。停止する場合は Ctrl+C 。
python server.py

pause
