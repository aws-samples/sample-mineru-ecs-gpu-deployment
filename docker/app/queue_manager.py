#!/usr/bin/env python3
"""
SQS队列管理器
处理任务消息的接收和删除
"""

import os
import json
from typing import List, Dict, Any, Optional

import boto3
import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger()

class SQSQueueManager:
    """SQS队列管理器"""
    
    def __init__(self):
        self.sqs_client = boto3.client('sqs')
        self.queue_url = os.getenv('SQS_QUEUE_URL')
        
        if not self.queue_url:
            raise ValueError("SQS_QUEUE_URL环境变量未设置")
        
        logger.info("SQS队列管理器初始化", queue_url=self.queue_url)
    
    def receive_messages(self, max_messages: int = 1, 
                        wait_time_seconds: int = 20) -> List[Dict[str, Any]]:
        """
        从SQS队列接收消息
        
        Args:
            max_messages: 最大消息数量
            wait_time_seconds: 长轮询等待时间
            
        Returns:
            消息列表
        """
        try:
            response = self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time_seconds,
                MessageAttributeNames=['All'],
                AttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            
            if messages:
                logger.info("接收到SQS消息", count=len(messages))
                
                # 解析消息内容
                for message in messages:
                    try:
                        body = json.loads(message['Body'])
                        message['ParsedBody'] = body
                        logger.debug("消息解析成功", 
                                   message_id=message['MessageId'],
                                   job_id=body.get('job_id'))
                    except json.JSONDecodeError as e:
                        logger.error("消息解析失败", 
                                   message_id=message['MessageId'],
                                   error=str(e))
            
            return messages
            
        except ClientError as e:
            logger.error("接收SQS消息失败", error=str(e))
            raise
        except Exception as e:
            logger.error("SQS操作异常", error=str(e))
            raise
    
    def delete_message(self, message: Dict[str, Any]) -> bool:
        """
        删除SQS消息
        
        Args:
            message: 要删除的消息
            
        Returns:
            删除是否成功
        """
        try:
            receipt_handle = message['ReceiptHandle']
            
            self.sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            
            logger.info("SQS消息删除成功", message_id=message['MessageId'])
            return True
            
        except ClientError as e:
            logger.error("删除SQS消息失败", 
                        message_id=message.get('MessageId'),
                        error=str(e))
            return False
        except Exception as e:
            logger.error("删除消息异常", error=str(e))
            return False
    
    def change_message_visibility(self, message: Dict[str, Any], 
                                visibility_timeout: int) -> bool:
        """
        修改消息可见性超时
        
        Args:
            message: 消息对象
            visibility_timeout: 新的可见性超时时间(秒)
            
        Returns:
            修改是否成功
        """
        try:
            receipt_handle = message['ReceiptHandle']
            
            self.sqs_client.change_message_visibility(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout
            )
            
            logger.info("消息可见性超时修改成功", 
                       message_id=message['MessageId'],
                       visibility_timeout=visibility_timeout)
            return True
            
        except ClientError as e:
            logger.error("修改消息可见性失败", 
                        message_id=message.get('MessageId'),
                        error=str(e))
            return False
    
    def get_queue_attributes(self) -> Dict[str, str]:
        """
        获取队列属性
        
        Returns:
            队列属性字典
        """
        try:
            response = self.sqs_client.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=[
                    'ApproximateNumberOfMessages',
                    'ApproximateNumberOfMessagesNotVisible',
                    'ApproximateNumberOfMessagesDelayed'
                ]
            )
            
            attributes = response.get('Attributes', {})
            logger.debug("获取队列属性成功", attributes=attributes)
            return attributes
            
        except ClientError as e:
            logger.error("获取队列属性失败", error=str(e))
            return {}
    
    def send_message(self, message_body: Dict[str, Any], 
                    message_group_id: str = 'processing',
                    deduplication_id: Optional[str] = None) -> bool:
        """
        发送消息到队列 (主要用于测试)
        
        Args:
            message_body: 消息内容
            message_group_id: 消息组ID
            deduplication_id: 去重ID
            
        Returns:
            发送是否成功
        """
        try:
            params = {
                'QueueUrl': self.queue_url,
                'MessageBody': json.dumps(message_body),
                'MessageGroupId': message_group_id
            }
            
            if deduplication_id:
                params['MessageDeduplicationId'] = deduplication_id
            
            response = self.sqs_client.send_message(**params)
            
            logger.info("消息发送成功", 
                       message_id=response['MessageId'],
                       job_id=message_body.get('job_id'))
            return True
            
        except ClientError as e:
            logger.error("发送消息失败", error=str(e))
            return False
    
    def purge_queue(self) -> bool:
        """
        清空队列 (谨慎使用)
        
        Returns:
            清空是否成功
        """
        try:
            self.sqs_client.purge_queue(QueueUrl=self.queue_url)
            logger.warning("队列已清空")
            return True
            
        except ClientError as e:
            logger.error("清空队列失败", error=str(e))
            return False
