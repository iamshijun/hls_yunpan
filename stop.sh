#!/bin/bash

# 停止后台运行的 Yunpan HLS Proxy

PID_FILE="server.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "未找到 PID 文件 ($PID_FILE)，服务可能未在后台运行"
    exit 0
fi

PID=$(cat "$PID_FILE" 2>/dev/null)

if [ -z "$PID" ]; then
    echo "PID 文件为空，清理残留文件"
    rm -f "$PID_FILE"
    exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
    echo "进程 $PID 不存在，服务可能已停止，清理残留文件"
    rm -f "$PID_FILE"
    exit 0
fi

echo "正在停止 Yunpan HLS Proxy (PID: $PID)..."

# 先停止 reloader 的子进程（忽略不支持 -P 选项的错误）
pkill -TERM -P "$PID" 2>/dev/null
# 停止主进程
kill -TERM "$PID" 2>/dev/null

# 等待进程退出（最多 10 秒）
for i in $(seq 1 10); do
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 1
done

# 若仍未退出，强制结束
if kill -0 "$PID" 2>/dev/null; then
    echo "进程未响应 SIGTERM，强制结束..."
    pkill -KILL -P "$PID" 2>/dev/null
    kill -KILL "$PID" 2>/dev/null
fi

rm -f "$PID_FILE"
echo "服务已停止"
