#!/usr/bin/env python3
"""
DynamoDB任务管理器
处理任务状态的读取和更新
"""

import os
import time
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime, timezone, timedelta

import boto3
import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger()

def timestamp_to_beijing_str(timestamp):
    """
    将时间戳转换为北京时间字符串格式 (BJT)
    
    Args:
        timestamp: Unix时间戳 (float或Decimal)
        
    Returns:
        格式化的北京时间字符串，例如: "2025-07-16 07:27:19 BJT"
    """
    if isinstance(timestamp, Decimal):
        timestamp = float(timestamp)
    
    # 创建UTC时间
    dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    
    # 转换为北京时间 (UTC+8)
    beijing_tz = timezone(timedelta(hours=8))
    dt_beijing = dt_utc.astimezone(beijing_tz)
    
    # 格式化为指定格式
    return dt_beijing.strftime("%Y-%m-%d %H:%M:%S BJT")

class DynamoDBJobManager:
    """DynamoDB任务管理器"""
    
    def _convert_floats_to_decimal(self, obj):
        """
        递归地将对象中的float类型转换为Decimal类型
        DynamoDB不支持原生的float类型
        
        Args:
            obj: 要转换的对象
            
        Returns:
            转换后的对象
        """
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {key: self._convert_floats_to_decimal(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimal(item) for item in obj]
        else:
            return obj
    
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.table_name = os.getenv('DYNAMODB_TABLE')
        
        if not self.table_name:
            raise ValueError("DYNAMODB_TABLE环境变量未设置")
        
        self.table = self.dynamodb.Table(self.table_name)
        
        logger.info("DynamoDB任务管理器初始化", table_name=self.table_name)
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务详情
        
        Args:
            job_id: 任务ID
            
        Returns:
            任务详情字典，如果不存在返回None
        """
        try:
            response = self.table.get_item(Key={'job_id': job_id})
            
            if 'Item' in response:
                job = response['Item']
                logger.debug("获取任务成功", job_id=job_id, status=job.get('status'))
                return job
            else:
                logger.warning("任务不存在", job_id=job_id)
                return None
                
        except ClientError as e:
            logger.error("获取任务失败", job_id=job_id, error=str(e))
            raise
    
    def update_job_status(self, job_id: str, status: str, **kwargs) -> bool:
        """
        更新任务状态
        
        Args:
            job_id: 任务ID
            status: 新状态
            **kwargs: 其他要更新的字段
            
        Returns:
            更新是否成功
        """
        try:
            # 构建更新表达式
            update_expression = "SET #status = :status, updated_at = :updated_at"
            expression_attribute_names = {'#status': 'status'}
            
            # 当前时间戳转换为北京时间字符串
            current_time = time.time()
            expression_attribute_values = {
                ':status': status,
                ':updated_at': timestamp_to_beijing_str(current_time)
            }
            
            # 添加其他字段
            for key, value in kwargs.items():
                if value is not None:
                    attr_name = f"#{key}"
                    attr_value = f":{key}"
                    
                    update_expression += f", {attr_name} = {attr_value}"
                    expression_attribute_names[attr_name] = key
                    
                    # 处理不同类型的值
                    if isinstance(value, (int, float, Decimal)) and key in ['started_at', 'completed_at', 'received_at', 'failed_at']:
                        # 将时间戳转换为北京时间字符串
                        expression_attribute_values[attr_value] = timestamp_to_beijing_str(value)
                    else:
                        # 使用递归函数转换所有float类型为Decimal类型
                        expression_attribute_values[attr_value] = self._convert_floats_to_decimal(value)
            
            # 执行更新
            response = self.table.update_item(
                Key={'job_id': job_id},
                UpdateExpression=update_expression,
                ExpressionAttributeNames=expression_attribute_names,
                ExpressionAttributeValues=expression_attribute_values,
                ReturnValues='UPDATED_NEW'
            )
            
            logger.info("任务状态更新成功", 
                       job_id=job_id, 
                       status=status,
                       updated_fields=list(kwargs.keys()))
            return True
            
        except ClientError as e:
            logger.error("更新任务状态失败", 
                        job_id=job_id, 
                        status=status,
                        error=str(e))
            return False
    
    def query_jobs_by_status(self, status: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        根据状态查询任务
        
        Args:
            status: 任务状态
            limit: 返回数量限制
            
        Returns:
            任务列表
        """
        try:
            response = self.table.query(
                IndexName='status-created_at-index',
                KeyConditionExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': status},
                Limit=limit,
                ScanIndexForward=True  # 按创建时间升序
            )
            
            jobs = response.get('Items', [])
            logger.debug("查询任务成功", status=status, count=len(jobs))
            return jobs
            
        except ClientError as e:
            logger.error("查询任务失败", status=status, error=str(e))
            return []
    
    def query_jobs_by_worker(self, worker_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        根据工作节点查询任务
        
        Args:
            worker_id: 工作节点ID
            limit: 返回数量限制
            
        Returns:
            任务列表
        """
        try:
            response = self.table.query(
                IndexName='worker_id-index',
                KeyConditionExpression='worker_id = :worker_id',
                ExpressionAttributeValues={':worker_id': worker_id},
                Limit=limit
            )
            
            jobs = response.get('Items', [])
            logger.debug("查询工作节点任务成功", worker_id=worker_id, count=len(jobs))
            return jobs
            
        except ClientError as e:
            logger.error("查询工作节点任务失败", worker_id=worker_id, error=str(e))
            return []
    
    def increment_retry_count(self, job_id: str) -> int:
        """
        增加重试次数
        
        Args:
            job_id: 任务ID
            
        Returns:
            新的重试次数
        """
        try:
            response = self.table.update_item(
                Key={'job_id': job_id},
                UpdateExpression='ADD retry_count :inc SET updated_at = :updated_at',
                ExpressionAttributeValues={
                    ':inc': 1,
                    ':updated_at': Decimal(str(time.time()))
                },
                ReturnValues='UPDATED_NEW'
            )
            
            new_retry_count = int(response['Attributes']['retry_count'])
            logger.info("重试次数增加", job_id=job_id, retry_count=new_retry_count)
            return new_retry_count
            
        except ClientError as e:
            logger.error("增加重试次数失败", job_id=job_id, error=str(e))
            return 0
    
    def get_job_statistics(self) -> Dict[str, int]:
        """
        获取任务统计信息
        
        Returns:
            统计信息字典
        """
        try:
            stats = {
                'pending': 0,
                'processing': 0,
                'completed': 0,
                'failed': 0,
                'total': 0
            }
            
            # 扫描表获取统计信息 (注意：大表慎用)
            response = self.table.scan(
                ProjectionExpression='#status',
                ExpressionAttributeNames={'#status': 'status'}
            )
            
            for item in response.get('Items', []):
                status = item.get('status', 'unknown')
                if status in stats:
                    stats[status] += 1
                stats['total'] += 1
            
            # 处理分页
            while 'LastEvaluatedKey' in response:
                response = self.table.scan(
                    ProjectionExpression='#status',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                
                for item in response.get('Items', []):
                    status = item.get('status', 'unknown')
                    if status in stats:
                        stats[status] += 1
                    stats['total'] += 1
            
            logger.info("获取任务统计成功", stats=stats)
            return stats
            
        except ClientError as e:
            logger.error("获取任务统计失败", error=str(e))
            return {}
    
    def cleanup_old_jobs(self, days: int = 30) -> int:
        """
        清理旧任务记录
        
        Args:
            days: 保留天数
            
        Returns:
            删除的任务数量
        """
        try:
            cutoff_time = time.time() - (days * 24 * 3600)
            cutoff_decimal = Decimal(str(cutoff_time))
            
            # 扫描旧任务
            response = self.table.scan(
                FilterExpression='created_at < :cutoff',
                ExpressionAttributeValues={':cutoff': cutoff_decimal},
                ProjectionExpression='job_id'
            )
            
            deleted_count = 0
            
            # 批量删除
            with self.table.batch_writer() as batch:
                for item in response.get('Items', []):
                    batch.delete_item(Key={'job_id': item['job_id']})
                    deleted_count += 1
            
            # 处理分页
            while 'LastEvaluatedKey' in response:
                response = self.table.scan(
                    FilterExpression='created_at < :cutoff',
                    ExpressionAttributeValues={':cutoff': cutoff_decimal},
                    ProjectionExpression='job_id',
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                
                with self.table.batch_writer() as batch:
                    for item in response.get('Items', []):
                        batch.delete_item(Key={'job_id': item['job_id']})
                        deleted_count += 1
            
            logger.info("清理旧任务完成", deleted_count=deleted_count, days=days)
            return deleted_count
            
        except ClientError as e:
            logger.error("清理旧任务失败", error=str(e))
            return 0
