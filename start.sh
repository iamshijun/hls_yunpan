#!/bin/bash

# 启动脚本

echo "正在启动 Yunpan HLS Proxy..."

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python3，请先安装Python3"
    exit 1
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -r requirements.txt

# 检查.env文件
if [ ! -f ".env" ]; then
    echo "警告: .env文件不存在，使用.env.example创建..."
    cp .env.example .env
    echo "请编辑.env文件并配置百度网盘token信息"
fi

# 创建缓存目录
mkdir -p cache

# 启动服务
echo "启动服务..."
python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 9009 \
    --reload \
    --timeout-keep-alive 30
