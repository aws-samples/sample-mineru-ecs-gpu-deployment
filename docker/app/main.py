#!/usr/bin/env python3
"""
MinerU混合架构处理器主程序
支持GPU节点和CPU模式自动检测
"""

import os
import sys
import time
import json
import logging
import signal
import threading
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import structlog
import torch
from flask import Flask, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest

from processor import MinerUProcessor
from queue_manager import SQSQueueManager
from job_manager import DynamoDBJobManager, timestamp_to_beijing_str
from health_checker import HealthChecker

# 首先配置标准logging，确保所有日志都能输出
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)

# 设置第三方库日志级别
logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# 配置结构化日志
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus指标
JOBS_PROCESSED = Counter('mineru_jobs_processed_total', 'Total processed jobs', ['status', 'device_type'])
PROCESSING_TIME = Histogram('mineru_processing_duration_seconds', 'Job processing time')
ACTIVE_JOBS = Gauge('mineru_active_jobs', 'Currently active jobs')
QUEUE_SIZE = Gauge('mineru_queue_size', 'SQS queue size')

class MinerUHybridProcessor:
    """MinerU混合架构处理器 - 支持GPU/CPU自动检测"""
    
    def __init__(self):
        self.compute_mode = os.getenv('COMPUTE_MODE', 'auto')
        self.single_task_mode = os.getenv('SINGLE_TASK_MODE', 'false').lower() == 'true'
        self.job_id = os.getenv('JOB_ID')  # Fargate模式下的特定任务ID
        
        # GPU设置 - 支持自动检测
        gpu_env = os.getenv('ENABLE_GPU', 'auto').lower()
        if gpu_env == 'auto':
            self.enable_gpu = None  # 让 MinerUProcessor 自动检测
        else:
            self.enable_gpu = gpu_env in ['true', '1', 'yes']
        
        # 检测实际的设备类型
        self.device_type = 'gpu' if torch.cuda.is_available() else 'cpu'
        
        self.running = True
        self.current_job = None
        
        logger.info("处理器初始化",
                   compute_mode=self.compute_mode,
                   enable_gpu_setting=gpu_env,
                   device_type=self.device_type,
                   cuda_available=torch.cuda.is_available(),
                   single_task_mode=self.single_task_mode)
        
        # 初始化组件
        self.processor = MinerUProcessor(enable_gpu=self.enable_gpu)
        self.queue_manager = SQSQueueManager()
        self.job_manager = DynamoDBJobManager()
        self.health_checker = HealthChecker()
        
        # Flask应用 (健康检查和指标)
        self.app = Flask(__name__)
        self.setup_flask_routes()
        
        # 信号处理
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        logger.info("MinerU处理器初始化完成", 
                   compute_mode=self.compute_mode,
                   single_task_mode=self.single_task_mode,
                   enable_gpu=self.enable_gpu,
                   job_id=self.job_id)
    
    def setup_flask_routes(self):
        """设置Flask路由"""
        
        @self.app.route('/health')
        def health():
            """健康检查端点"""
            health_status = self.health_checker.check_health()
            # 添加设备类型信息
            health_status['device_type'] = self.device_type
            health_status['gpu_available'] = torch.cuda.is_available()
            if torch.cuda.is_available():
                health_status['gpu_count'] = torch.cuda.device_count()
                health_status['gpu_name'] = torch.cuda.get_device_name(0)
            status_code = 200 if health_status['healthy'] else 503
            return jsonify(health_status), status_code
        
        @self.app.route('/ready')
        def ready():
            """就绪检查端点"""
            ready_status = self.health_checker.check_readiness()
            status_code = 200 if ready_status['ready'] else 503
            return jsonify(ready_status), status_code
        
        @self.app.route('/metrics')
        def metrics():
            """Prometheus指标端点"""
            return generate_latest()
        
        @self.app.route('/status')
        def status():
            """状态信息端点"""
            return jsonify({
                'compute_mode': self.compute_mode,
                'single_task_mode': self.single_task_mode,
                'enable_gpu': self.enable_gpu,
                'current_job': self.current_job,
                'running': self.running,
                'uptime': time.time() - self.start_time
            })
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        logger.info("收到终止信号", signal=signum)
        self.running = False
        
        # 如果正在处理任务，标记为中断
        if self.current_job:
            try:
                self.job_manager.update_job_status(
                    self.current_job['job_id'],
                    'interrupted',
                    error_message='收到终止信号，任务被中断'
                )
            except Exception as e:
                logger.error("更新任务状态失败", error=str(e))
    
    def run_gpu_mode(self):
        """ECS GPU模式 - 持续监听SQS队列，处理所有任务"""
        logger.info("启动ECS GPU模式")
        
        poll_interval = int(os.getenv('POLL_INTERVAL', '5'))
        
        while self.running:
            try:
                # 从SQS接收消息
                messages = self.queue_manager.receive_messages(max_messages=1)
                
                if messages:
                    for message in messages:
                        if not self.running:
                            break
                        
                        try:
                            # 解析任务数据
                            job_data = json.loads(message['Body'])
                            
                            # ECS模式处理所有任务，不进行模式过滤
                            logger.info("接收到任务", 
                                      job_id=job_data.get('job_id'),
                                      device_type=self.device_type)
                            
                            # 计算队列等待时间
                            sent_time = float(message['Attributes']['SentTimestamp']) / 1000
                            receive_time = time.time()
                            queue_wait_time = receive_time - sent_time
                            
                            # 添加队列等待时间到任务数据
                            job_data['queue_wait_time'] = queue_wait_time
                            job_data['received_at'] = receive_time
                            job_data['processor_device'] = self.device_type
                            
                            # 处理任务
                            self.process_job(job_data)
                            
                            # 删除SQS消息
                            self.queue_manager.delete_message(message)
                            
                        except Exception as e:
                            logger.error("处理任务失败", error=str(e), message=message)
                            JOBS_PROCESSED.labels(status='failed', device_type=self.device_type).inc()
                else:
                    # 更新队列大小指标
                    try:
                        queue_attrs = self.queue_manager.get_queue_attributes()
                        QUEUE_SIZE.set(int(queue_attrs.get('ApproximateNumberOfMessages', 0)))
                    except Exception as e:
                        logger.warning("获取队列属性失败", error=str(e))
                    
                    # 短暂休眠
                    time.sleep(poll_interval)
                    
            except Exception as e:
                logger.error("ECS GPU模式运行错误", error=str(e))
                time.sleep(poll_interval)
    
    def run_fargate_mode(self):
        """Fargate模式 - 处理单个任务后退出"""
        logger.info("启动Fargate模式", job_id=self.job_id)
        
        if not self.job_id:
            logger.error("Fargate模式需要JOB_ID环境变量")
            sys.exit(1)
        
        try:
            # 从DynamoDB获取任务详情
            job_data = self.job_manager.get_job(self.job_id)
            if not job_data:
                logger.error("未找到任务", job_id=self.job_id)
                sys.exit(1)
            
            # 处理任务
            self.process_job(job_data)
            
            logger.info("Fargate任务处理完成", job_id=self.job_id)
            
        except Exception as e:
            logger.error("Fargate模式处理失败", error=str(e), job_id=self.job_id)
            sys.exit(1)
    
    def process_job(self, job_data: Dict[str, Any]):
        """处理单个任务"""
        job_id = job_data['job_id']
        self.current_job = job_data
        
        logger.info("开始处理任务", job_id=job_id, compute_mode=self.compute_mode)
        ACTIVE_JOBS.inc()
        
        start_time = time.time()
        
        try:
            # 更新任务状态为处理中，包含队列等待时间
            update_data = {
                'worker_id': self.get_worker_id(),
                'started_at': timestamp_to_beijing_str(start_time)
            }
            
            # 如果有队列等待时间信息，添加到更新数据中
            if 'queue_wait_time' in job_data:
                update_data['queue_wait_time'] = job_data['queue_wait_time']
            if 'received_at' in job_data:
                update_data['received_at'] = timestamp_to_beijing_str(job_data['received_at'])
            
            self.job_manager.update_job_status(
                job_id, 
                'processing',
                **update_data
            )
            
            # 执行MinerU处理
            with PROCESSING_TIME.time():
                result = self.processor.process_pdf(
                    data_bucket=job_data['data_bucket'],
                    input_key=job_data['input_key'],
                    output_prefix=job_data['output_prefix'],
                    job_id=job_id
                )
            
            processing_time = time.time() - start_time
            
            # 更新任务状态为完成
            self.job_manager.update_job_status(
                job_id,
                'completed',
                completed_at=timestamp_to_beijing_str(time.time()),
                processing_time=processing_time,
                result=result
            )
            
            JOBS_PROCESSED.labels(status='completed', device_type=self.device_type).inc()
            logger.info("任务处理完成", job_id=job_id, duration=processing_time)
            
        except Exception as e:
            # 更新任务状态为失败
            self.job_manager.update_job_status(
                job_id,
                'failed',
                error_message=str(e),
                failed_at=timestamp_to_beijing_str(time.time())
            )
            
            JOBS_PROCESSED.labels(status='failed', device_type=self.device_type).inc()
            logger.error("任务处理失败", job_id=job_id, error=str(e))
            
            if self.single_task_mode:
                raise
        
        finally:
            ACTIVE_JOBS.dec()
            self.current_job = None
    
    def get_worker_id(self) -> str:
        """获取工作节点ID"""
        hostname = os.getenv('HOSTNAME', 'unknown')
        if self.compute_mode == 'fargate':
            return f"fargate-{hostname}"
        elif self.compute_mode == 'gpu':
            return f"gpu-{hostname}"
        else:
            return f"worker-{hostname}"
    
    def start_flask_server(self):
        """启动Flask服务器"""
        def run_server():
            self.app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
        
        flask_thread = threading.Thread(target=run_server, daemon=True)
        flask_thread.start()
        logger.info("Flask服务器已启动", port=8080)
    
    def run(self):
        """主运行方法"""
        self.start_time = time.time()
        
        # 启动Flask服务器
        self.start_flask_server()
        
        # 等待服务就绪
        time.sleep(2)
        
        try:
            if self.single_task_mode:
                # Fargate模式
                self.run_fargate_mode()
            else:
                # GPU节点模式
                self.run_gpu_mode()
        
        except KeyboardInterrupt:
            logger.info("收到键盘中断信号")
        except Exception as e:
            logger.error("运行时错误", error=str(e))
            raise
        finally:
            logger.info("MinerU处理器停止")

def main():
    """主函数"""
    try:
        processor = MinerUHybridProcessor()
        processor.run()
    except Exception as e:
        logger.error("启动失败", error=str(e))
        sys.exit(1)

if __name__ == '__main__':
    main()
