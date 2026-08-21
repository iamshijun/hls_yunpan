#!/bin/bash

# 启动脚本
# 默认后台运行，指定 -f 参数在前台运行
# 端口来自 .env（PORT），默认 8000；实际监听由 config/settings.py 决定。

FOREGROUND=false
for arg in "$@"; do
    case "$arg" in
        -f|--foreground) FOREGROUND=true ;;
        -h|--help)
            echo "用法: $0 [-f]"
            echo "  -f, --foreground  在前台运行 (默认后台运行)"
            exit 0
            ;;
        *)
            echo "错误: 未知参数: $arg"
            echo "用法: $0 [-f]"
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="server.pid"
LOG_FILE="server.log"

# 检查是否已有实例在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "检测到已有实例正在运行 (PID: $OLD_PID)"
        echo "如需停止请运行: ./stop.sh"
        exit 1
    fi
    echo "清理过期的 PID 文件..."
    rm -f "$PID_FILE"
fi

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

# 读取 .env（若存在）注入环境变量，让 config/settings.py 读取 PORT/HOST 等
set -a
. ./.env
set +a

# 默认端口与 config/settings.py 保持一致：8000
PORT="${PORT:-8000}"

# 创建缓存目录
mkdir -p cache

print_addresses() {
    echo "访问地址:"
    echo "- 本地访问: http://localhost:$PORT/"
    echo "- 网络访问: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT/"
}

if [ "$FOREGROUND" = true ]; then
    echo "前台模式启动..."
    print_addresses
    echo ""
    exec python -m app.main
else
    echo "后台模式启动，日志写入: $LOG_FILE"
    nohup python -m app.main > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    # 等待并确认启动
    sleep 2
    if kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
        echo "服务已在后台启动 (PID: $(cat "$PID_FILE"))"
        print_addresses
        echo ""
        echo "停止服务: ./stop.sh"
        echo "查看日志: tail -f $LOG_FILE"
    else
        echo "启动失败，请查看日志: tail -f $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
fi
