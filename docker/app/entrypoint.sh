#!/bin/bash
set -e

# MinerU v3 ECS GPU容器入口脚本

echo "=== MinerU v3 处理器启动 ==="
echo "Backend: ${MINERU_BACKEND:-hybrid-auto-engine}"
echo "设备模式: ${MINERU_DEVICE_MODE:-cuda}"
echo "模型来源: ${MINERU_MODEL_SOURCE:-local}"
echo "时间: $(date)"

# 检查必需的环境变量
required_vars=("DYNAMODB_TABLE" "SQS_QUEUE_URL")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "错误: 环境变量 $var 未设置"
        exit 1
    fi
done

# 创建必要的目录
mkdir -p /tmp/mineru-workspace /tmp/input /tmp/output /app/logs
chmod 755 /tmp/mineru-workspace /tmp/input /tmp/output

# GPU环境检查
echo "=== GPU环境检查 ==="
if command -v nvidia-smi &> /dev/null; then
    echo "NVIDIA驱动信息:"
    nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader,nounits || true
else
    echo "警告: nvidia-smi 不可用"
fi

# PyTorch GPU测试
echo "PyTorch GPU测试:"
python3 -c "
import torch
print(f'  PyTorch版本: {torch.__version__}')
print(f'  CUDA可用: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU数量: {torch.cuda.device_count()}')
    for i in range(torch.cuda.device_count()):
        print(f'  GPU {i}: {torch.cuda.get_device_name(i)}')
        props = torch.cuda.get_device_properties(i)
        print(f'    显存: {props.total_memory / 1024**3:.1f} GB')
" || echo "PyTorch GPU检测失败"

# MinerU验证
echo "=== MinerU验证 ==="
python3 -c "
from mineru.version import __version__
print(f'MinerU版本: {__version__}')
" || echo "MinerU导入失败"

# 检查mineru CLI
if command -v mineru &> /dev/null; then
    echo "✓ mineru CLI可用"
else
    echo "✗ mineru CLI不可用"
    exit 1
fi

# 依赖检查
echo "=== 依赖检查 ==="
python3 -c "
import boto3
print(f'✓ boto3: {boto3.__version__}')
import torch
print(f'✓ torch: {torch.__version__}')
print(f'✓ CUDA available: {torch.cuda.is_available()}')
try:
    import vllm
    print(f'✓ vllm: available')
except ImportError:
    print('⚠ vllm: not available, will fallback to transformers')
"

# AWS连接检查
echo "=== AWS连接检查 ==="
python3 -c "
import boto3
import os
try:
    sts = boto3.client('sts')
    identity = sts.get_caller_identity()
    print(f'✓ AWS身份: {identity[\"Arn\"]}')
except Exception as e:
    print(f'✗ AWS身份验证失败: {e}')

try:
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])
    status = table.table_status
    print(f'✓ DynamoDB表状态: {status}')
except Exception as e:
    print(f'✗ DynamoDB连接失败: {e}')

try:
    sqs = boto3.client('sqs')
    attrs = sqs.get_queue_attributes(
        QueueUrl=os.environ['SQS_QUEUE_URL'],
        AttributeNames=['QueueArn']
    )
    print(f'✓ SQS队列: {attrs[\"Attributes\"][\"QueueArn\"]}')
except Exception as e:
    print(f'✗ SQS连接失败: {e}')
"

# 系统资源
echo "=== 系统资源 ==="
echo "CPU核心数: $(nproc)"
echo "内存总量: $(free -h | awk '/^Mem:/ {print $2}')"
echo "磁盘空间: $(df -h / | awk 'NR==2 {print $4\" available\"}')"

echo "✓ 所有检查通过"
echo "=== 启动应用程序 ==="

# 启动
if [ "$#" -eq 0 ]; then
    exec python3 main.py
else
    exec "$@"
fi
