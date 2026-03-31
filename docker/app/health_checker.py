#!/usr/bin/env python3
"""
健康检查器
提供应用健康状态和就绪状态检查
"""

import os
import time
import psutil
from typing import Dict, Any, List

import boto3
import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger()

class HealthChecker:
    """健康检查器"""
    
    def __init__(self):
        self.start_time = time.time()
        self.enable_gpu = os.getenv('ENABLE_GPU', 'true').lower() == 'true'
        self.compute_mode = os.getenv('COMPUTE_MODE', 'gpu-nodes')
        
        # AWS客户端
        self.s3_client = boto3.client('s3')
        self.dynamodb = boto3.resource('dynamodb')
        self.sqs_client = boto3.client('sqs')
        
        # 配置参数
        self.table_name = os.getenv('DYNAMODB_TABLE')
        self.queue_url = os.getenv('SQS_QUEUE_URL')
        
        logger.info("健康检查器初始化", 
                   enable_gpu=self.enable_gpu,
                   compute_mode=self.compute_mode)
    
    def check_health(self) -> Dict[str, Any]:
        """
        综合健康检查
        
        Returns:
            健康状态字典
        """
        health_status = {
            'healthy': True,
            'timestamp': time.time(),
            'uptime': time.time() - self.start_time,
            'checks': {}
        }
        
        # 系统资源检查
        health_status['checks']['system'] = self._check_system_resources()
        
        # GPU检查 (如果启用)
        if self.enable_gpu:
            health_status['checks']['gpu'] = self._check_gpu_status()
        
        # AWS服务连接检查
        health_status['checks']['aws'] = self._check_aws_connectivity()
        
        # 工作目录检查
        health_status['checks']['workspace'] = self._check_workspace()
        
        # 判断整体健康状态
        for check_name, check_result in health_status['checks'].items():
            if not check_result.get('healthy', False):
                health_status['healthy'] = False
                logger.warning("健康检查失败", check=check_name, result=check_result)
        
        if health_status['healthy']:
            logger.debug("健康检查通过")
        else:
            logger.error("健康检查失败", status=health_status)
        
        return health_status
    
    def check_readiness(self) -> Dict[str, Any]:
        """
        就绪状态检查
        
        Returns:
            就绪状态字典
        """
        readiness_status = {
            'ready': True,
            'timestamp': time.time(),
            'checks': {}
        }
        
        # AWS服务可用性检查
        readiness_status['checks']['aws_services'] = self._check_aws_services()
        
        # 依赖服务检查
        readiness_status['checks']['dependencies'] = self._check_dependencies()
        
        # 判断整体就绪状态
        for check_name, check_result in readiness_status['checks'].items():
            if not check_result.get('ready', False):
                readiness_status['ready'] = False
                logger.warning("就绪检查失败", check=check_name, result=check_result)
        
        if readiness_status['ready']:
            logger.debug("就绪检查通过")
        else:
            logger.error("就绪检查失败", status=readiness_status)
        
        return readiness_status
    
    def _check_system_resources(self) -> Dict[str, Any]:
        """检查系统资源"""
        try:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # 内存使用情况
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # 磁盘使用情况
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            
            # 负载平均值
            load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
            
            # 健康阈值检查
            healthy = (
                cpu_percent < 95 and
                memory_percent < 95 and
                disk_percent < 90
            )
            
            return {
                'healthy': healthy,
                'cpu_percent': cpu_percent,
                'memory_percent': memory_percent,
                'disk_percent': disk_percent,
                'load_avg': load_avg,
                'memory_available_gb': memory.available / (1024**3),
                'disk_free_gb': disk.free / (1024**3)
            }
            
        except Exception as e:
            logger.error("系统资源检查失败", error=str(e))
            return {'healthy': False, 'error': str(e)}
    
    def _check_gpu_status(self) -> Dict[str, Any]:
        """检查GPU状态"""
        try:
            import torch
            
            # 检查CUDA可用性
            cuda_available = torch.cuda.is_available()
            
            if cuda_available:
                # GPU设备信息
                device_count = torch.cuda.device_count()
                current_device = torch.cuda.current_device()
                device_name = torch.cuda.get_device_name(current_device)
                
                # GPU内存使用情况
                memory_allocated = torch.cuda.memory_allocated(current_device)
                memory_reserved = torch.cuda.memory_reserved(current_device)
                memory_total = torch.cuda.get_device_properties(current_device).total_memory
                
                memory_percent = (memory_reserved / memory_total) * 100
                
                return {
                    'healthy': True,
                    'cuda_available': cuda_available,
                    'device_count': device_count,
                    'current_device': current_device,
                    'device_name': device_name,
                    'memory_allocated_mb': memory_allocated / (1024**2),
                    'memory_reserved_mb': memory_reserved / (1024**2),
                    'memory_total_mb': memory_total / (1024**2),
                    'memory_percent': memory_percent
                }
            else:
                return {
                    'healthy': False,
                    'cuda_available': False,
                    'error': 'CUDA不可用'
                }
                
        except ImportError:
            return {
                'healthy': False,
                'error': 'PyTorch未安装'
            }
        except Exception as e:
            logger.error("GPU状态检查失败", error=str(e))
            return {'healthy': False, 'error': str(e)}
    
    def _check_aws_connectivity(self) -> Dict[str, Any]:
        """检查AWS服务连接"""
        aws_status = {
            'healthy': True,
            'services': {}
        }
        
        # 检查S3连接
        try:
            self.s3_client.list_buckets()
            aws_status['services']['s3'] = {'healthy': True}
        except Exception as e:
            aws_status['services']['s3'] = {'healthy': False, 'error': str(e)}
            aws_status['healthy'] = False
        
        # 检查DynamoDB连接
        if self.table_name:
            try:
                table = self.dynamodb.Table(self.table_name)
                table.table_status  # 触发连接
                aws_status['services']['dynamodb'] = {'healthy': True}
            except Exception as e:
                aws_status['services']['dynamodb'] = {'healthy': False, 'error': str(e)}
                aws_status['healthy'] = False
        
        # 检查SQS连接
        if self.queue_url:
            try:
                self.sqs_client.get_queue_attributes(
                    QueueUrl=self.queue_url,
                    AttributeNames=['QueueArn']
                )
                aws_status['services']['sqs'] = {'healthy': True}
            except Exception as e:
                aws_status['services']['sqs'] = {'healthy': False, 'error': str(e)}
                aws_status['healthy'] = False
        
        return aws_status
    
    def _check_workspace(self) -> Dict[str, Any]:
        """检查工作空间"""
        try:
            work_dir = os.getenv('WORK_DIR', '/tmp/mineru-workspace')
            
            # 检查目录是否存在和可写
            if not os.path.exists(work_dir):
                os.makedirs(work_dir, exist_ok=True)
            
            # 测试写入权限
            test_file = os.path.join(work_dir, '.health_check')
            with open(test_file, 'w') as f:
                f.write('health_check')
            
            # 清理测试文件
            os.remove(test_file)
            
            # 检查磁盘空间
            disk = psutil.disk_usage(work_dir)
            free_gb = disk.free / (1024**3)
            
            return {
                'healthy': free_gb > 1.0,  # 至少1GB可用空间
                'work_dir': work_dir,
                'writable': True,
                'free_space_gb': free_gb
            }
            
        except Exception as e:
            logger.error("工作空间检查失败", error=str(e))
            return {'healthy': False, 'error': str(e)}
    
    def _check_aws_services(self) -> Dict[str, Any]:
        """检查AWS服务可用性"""
        services_status = {
            'ready': True,
            'services': {}
        }
        
        # 检查DynamoDB表状态
        if self.table_name:
            try:
                table = self.dynamodb.Table(self.table_name)
                table_status = table.table_status
                
                services_status['services']['dynamodb'] = {
                    'ready': table_status == 'ACTIVE',
                    'status': table_status
                }
                
                if table_status != 'ACTIVE':
                    services_status['ready'] = False
                    
            except Exception as e:
                services_status['services']['dynamodb'] = {
                    'ready': False,
                    'error': str(e)
                }
                services_status['ready'] = False
        
        # 检查SQS队列状态
        if self.queue_url:
            try:
                attrs = self.sqs_client.get_queue_attributes(
                    QueueUrl=self.queue_url,
                    AttributeNames=['QueueArn', 'ApproximateNumberOfMessages']
                )
                
                services_status['services']['sqs'] = {
                    'ready': True,
                    'queue_arn': attrs['Attributes']['QueueArn'],
                    'message_count': int(attrs['Attributes']['ApproximateNumberOfMessages'])
                }
                
            except Exception as e:
                services_status['services']['sqs'] = {
                    'ready': False,
                    'error': str(e)
                }
                services_status['ready'] = False
        
        return services_status
    
    def _check_dependencies(self) -> Dict[str, Any]:
        """检查依赖服务"""
        deps_status = {
            'ready': True,
            'dependencies': {}
        }
        
        # 检查MinerU
        try:
            import mineru
            from mineru.version import __version__ as mineru_version
            from mineru.cli.common import do_parse
            deps_status['dependencies']['mineru'] = {
                'ready': True,
                'version': mineru_version,
                'api_available': True
            }
        except ImportError as e:
            deps_status['dependencies']['mineru'] = {
                'ready': False,
                'error': str(e)
            }
            deps_status['ready'] = False
        
        # 检查PyTorch (如果启用GPU)
        if self.enable_gpu:
            try:
                import torch
                deps_status['dependencies']['pytorch'] = {
                    'ready': True,
                    'version': torch.__version__,
                    'cuda_available': torch.cuda.is_available()
                }
            except ImportError as e:
                deps_status['dependencies']['pytorch'] = {
                    'ready': False,
                    'error': str(e)
                }
                deps_status['ready'] = False
        
        return deps_status
