#!/usr/bin/env bash
set -euo pipefail

cd /home/jonsen/project/daily_stock_analysis

if [ -f /home/jonsen/miniforge3/etc/profile.d/conda.sh ]; then
  source /home/jonsen/miniforge3/etc/profile.d/conda.sh
elif [ -f /home/jonsen/miniconda3/etc/profile.d/conda.sh ]; then
  source /home/jonsen/miniconda3/etc/profile.d/conda.sh
elif [ -f /home/jonsen/anaconda3/etc/profile.d/conda.sh ]; then
  source /home/jonsen/anaconda3/etc/profile.d/conda.sh
fi

conda activate stock

export NO_PROXY="localhost,127.0.0.1,::1,192.168.0.0/16,10.0.0.0/8"
export no_proxy="$NO_PROXY"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[1/3] Ollama probe (no project .env)..."
bash "${SCRIPT_DIR}/_ollama_probe.sh"

echo "[2/3] Dry-run stock data path..."
python main.py --dry-run --stocks 600519 --debug

echo "[3/3] Market review path..."
python main.py --market-review --no-notify --debug

echo "Smoke test completed."
