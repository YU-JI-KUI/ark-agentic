#!/bin/bash
# 启动脚本 - 使用 Mock 模式测试前端

# 设置环境变量
export SECURITIES_SERVICE_MOCK=true
export LLM_PROVIDER=mock

# 启动服务
echo "🚀 启动 ark-agentic 服务（Mock 模式）..."
echo "📍 访问地址: http://localhost:8080"
echo ""

uv run python -m ark_agentic.app
