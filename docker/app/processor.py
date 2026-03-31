#!/usr/bin/env python3
"""
MinerU PDF处理器 - 支持GPU/CPU自动检测
"""

import os
import shutil
import sys
import time
from typing import Dict, Any, Optional
from pathlib import Path
from decimal import Decimal

import boto3
import structlog
import torch
from job_manager import timestamp_to_beijing_str

logger = structlog.get_logger()

class MinerUProcessor:
    """MinerU PDF处理器 - 支持GPU/CPU自动检测"""
    
    def __init__(self, enable_gpu: Optional[bool] = None):
        # 默认启用GPU模式（信任容器环境）
        self.enable_gpu = True
        logger.info("MinerU处理器启动（GPU模式）")
        
        # 文件清理配置 - 从环境变量读取
        self.cleanup_files = os.getenv('CLEANUP_FILES', 'true').lower() == 'true'
        logger.info("文件清理配置", cleanup_enabled=self.cleanup_files)
        
        # 从环境变量读取GPU设置
        self.gpu_memory = int(os.getenv('MINERU_VIRTUAL_VRAM_SIZE', '12000'))
        
        # 处理参数
        self.language = os.getenv('MINERU_LANGUAGE', 'ch')
        self.backend = os.getenv('MINERU_BACKEND', 'hybrid-auto-engine')
        self.parse_method = os.getenv('MINERU_PARSE_METHOD', 'auto')
        self.formula_enable = os.getenv('MINERU_VLM_FORMULA_ENABLE', 'true').lower() == 'true'
        self.table_enable = os.getenv('MINERU_VLM_TABLE_ENABLE', 'true').lower() == 'true'
        
        # 工作目录
        self.work_dir = Path(os.getenv('MINERU_WORKSPACE', '/tmp/mineru-workspace'))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        # AWS客户端
        self.s3_client = boto3.client('s3')
        
        # 记录环境设置（不修改）
        self._log_environment_settings()
        
        logger.info("MinerU处理器初始化完成（信任容器环境）",
                   enable_gpu=self.enable_gpu,
                   gpu_memory=self.gpu_memory,
                   language=self.language,
                   backend=self.backend,
                   parse_method=self.parse_method)
    
    def _log_environment_settings(self):
        """记录当前环境设置（不修改）"""
        logger.info("当前环境设置记录",
                   device_mode=os.environ.get('MINERU_DEVICE_MODE', 'not_set'),
                   vram_size=os.environ.get('MINERU_VIRTUAL_VRAM_SIZE', 'not_set'),
                   cuda_visible=os.environ.get('CUDA_VISIBLE_DEVICES', 'not_set'),
                   nvidia_visible=os.environ.get('NVIDIA_VISIBLE_DEVICES', 'not_set'),
                   force_cuda=os.environ.get('FORCE_CUDA', 'not_set'),
                   formula_enable=os.environ.get('MINERU_VLM_FORMULA_ENABLE', 'not_set'),
                   table_enable=os.environ.get('MINERU_VLM_TABLE_ENABLE', 'not_set'))
    
    def validate_environment(self):
        """记录环境状态（不做强制验证）"""
        try:
            # 记录PyTorch状态
            logger.info("PyTorch环境状态",
                       version=torch.__version__,
                       cuda_available=torch.cuda.is_available(),
                       device_count=torch.cuda.device_count() if torch.cuda.is_available() else 0)
            
            if torch.cuda.is_available():
                try:
                    gpu_name = torch.cuda.get_device_name(0)
                    logger.info("GPU设备信息", device_name=gpu_name)
                except Exception as e:
                    logger.warning("无法获取GPU设备信息", error=str(e))
            else:
                logger.warning("PyTorch报告CUDA不可用，但继续执行（信任容器环境）")
                    
        except Exception as e:
            logger.warning("环境状态记录失败，但继续执行", error=str(e))
    
    def _estimate_page_count(self, pdf_bytes: bytes) -> int:
        """估算PDF页数"""
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(pdf_bytes)
            return len(pdf)
        except Exception:
            # 如果无法获取页数，返回估算值
            return max(1, len(pdf_bytes) // 50000)  # 粗略估算
    
    def process_pdf(self, data_bucket: str, input_key: str, 
                   output_prefix: str, job_id: str) -> Dict[str, Any]:
        """
        处理PDF文件
        
        Args:
            data_bucket: 统一数据S3存储桶
            input_key: 输入文件键 (包含input/前缀)
            output_prefix: 输出文件前缀 (output/{job_id}/)
            job_id: 任务ID
            
        Returns:
            处理结果字典
        """
        logger.info("开始处理PDF", 
                   data_bucket=data_bucket,
                   input_key=input_key,
                   output_prefix=output_prefix,
                   job_id=job_id,
                   gpu_enabled=self.enable_gpu)
        
        # 创建任务工作目录
        job_work_dir = self.work_dir / job_id
        job_work_dir.mkdir(parents=True, exist_ok=True)
        
        input_dir = job_work_dir / 'input'
        output_dir = job_work_dir / 'output'
        input_dir.mkdir(exist_ok=True)
        output_dir.mkdir(exist_ok=True)
        
        logger.info("工作目录创建完成",
                   job_work_dir=str(job_work_dir),
                   input_dir=str(input_dir),
                   output_dir=str(output_dir))
        
        try:
            # 1. 从S3下载PDF文件
            input_file = input_dir / Path(input_key).name
            logger.info("开始下载PDF文件", 
                       s3_path=f"s3://{data_bucket}/{input_key}",
                       local_path=str(input_file))
            
            download_start = time.time()
            self.s3_client.download_file(data_bucket, input_key, str(input_file))
            download_time = time.time() - download_start
            
            # 验证文件大小
            file_size = input_file.stat().st_size
            logger.info("文件下载完成", 
                       file_size=file_size,
                       file_size_mb=file_size / (1024*1024),
                       download_time=download_time)
            
            if file_size == 0:
                raise ValueError("下载的文件为空")
            
            # 2. 使用MinerU处理PDF
            logger.info("开始MinerU处理", compute_mode='gpu' if self.enable_gpu else 'cpu')
            processing_start = time.time()
            
            result = self._run_mineru_cli(input_file, output_dir)
            
            processing_time = time.time() - processing_start
            logger.info("MinerU处理完成", processing_time=processing_time)
            
            # 3. 上传结果到S3
            logger.info("开始上传结果到S3")
            upload_start = time.time()
            
            output_files = self._upload_results(output_dir, data_bucket, output_prefix)
            
            upload_time = time.time() - upload_start
            logger.info("结果上传完成", 
                       upload_time=upload_time,
                       uploaded_files_count=len(output_files))
            
            # 4. 清理临时文件（可配置）
            if self.cleanup_files:
                try:
                    shutil.rmtree(job_work_dir, ignore_errors=True)
                    logger.info("临时文件清理完成", job_work_dir=str(job_work_dir))
                except Exception as e:
                    logger.warning("临时文件清理失败", error=str(e))
            else:
                logger.info("跳过文件清理，文件保留在本地", job_work_dir=str(job_work_dir))
            
            processing_result = {
                'status': 'success',
                'input_file': f"s3://{data_bucket}/{input_key}",
                'output_files': output_files,
                'file_size': file_size,
                'pages_processed': result.get('pages', 0),
                'processing_time': result.get('processing_time', 0),
                'compute_mode': 'gpu' if self.enable_gpu else 'cpu',
                'download_time': download_time,
                'upload_time': upload_time,
                'total_files_generated': len(output_files)
            }
            
            logger.info("PDF处理完成", 
                       job_id=job_id,
                       result=processing_result)
            
            return processing_result
            
        except Exception as e:
            logger.error("PDF处理失败", 
                        job_id=job_id,
                        error=str(e),
                        error_type=type(e).__name__)
            
            # 清理临时文件（可配置）
            if self.cleanup_files:
                try:
                    shutil.rmtree(job_work_dir, ignore_errors=True)
                    logger.info("异常情况下临时文件清理完成")
                except:
                    pass
            else:
                logger.info("异常情况下保留文件用于调试", job_work_dir=str(job_work_dir))
            
            raise
    
    def _run_mineru_cli(self, input_file: Path, output_dir: Path) -> Dict[str, Any]:
        """
        使用MinerU Python API直接处理PDF（不走CLI/HTTP，避免超时问题）
        
        Args:
            input_file: 输入PDF文件路径
            output_dir: 输出目录路径
            
        Returns:
            处理结果
        """
        start_time = time.time()
        
        # 诊断处理环境
        self._diagnose_processing_environment(input_file, output_dir)
        
        # GPU状态记录
        if self.enable_gpu:
            try:
                logger.info("GPU状态查看", 
                           cuda_available=torch.cuda.is_available(),
                           device_count=torch.cuda.device_count(),
                           current_device=torch.cuda.current_device() if torch.cuda.is_available() else None)
                if torch.cuda.is_available():
                    logger.info("GPU设备信息", device_name=torch.cuda.get_device_name(0))
            except Exception as e:
                logger.warning("GPU状态查看失败", error=str(e))
        
        # 使用MinerU Python API直接调用
        from mineru.cli.common import do_parse, read_fn
        
        # 读取PDF文件为bytes
        pdf_bytes = read_fn(input_file)
        pdf_file_name = input_file.name
        
        logger.info("调用MinerU Python API",
                   backend=self.backend,
                   parse_method=self.parse_method,
                   language=self.language,
                   file_name=pdf_file_name)
        
        # 直接调用do_parse — 同步执行，无HTTP超时问题
        # hybrid-auto-engine 会自动选择 vllm-engine（同步模式）
        do_parse(
            output_dir=str(output_dir),
            pdf_file_names=[pdf_file_name],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=[self.language],
            backend=self.backend,
            parse_method=self.parse_method,
            formula_enable=self.formula_enable,
            table_enable=self.table_enable,
            f_dump_md=True,
            f_dump_middle_json=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=False,
        )
        
        processing_time = time.time() - start_time
        
        # 验证输出文件
        output_files = list(output_dir.rglob('*'))
        output_files = [f for f in output_files if f.is_file()]
        
        logger.info("MinerU处理完成", 
                   processing_time=processing_time,
                   output_files_count=len(output_files),
                   output_files=[f.name for f in output_files[:10]])
        
        if not output_files:
            raise RuntimeError("MinerU处理未生成任何输出文件")
        
        return {
            'pages': self._count_output_pages(output_dir),
            'processing_time': processing_time,
            'output_files_count': len(output_files),
            'success': True,
            'compute_mode': 'gpu' if self.enable_gpu else 'cpu',
        }
    
    def _count_output_pages(self, output_dir: Path) -> int:
        """从输出目录推断处理的页数"""
        try:
            md_files = list(output_dir.rglob('*.md'))
            if md_files:
                return len(md_files)
            return 1
        except Exception:
            return 0
    
    def _diagnose_processing_environment(self, input_file: Path, output_dir: Path):
        """诊断处理环境"""
        logger.info("=== 处理环境诊断 ===")
        
        # 检查输入文件
        if input_file.exists():
            file_size = input_file.stat().st_size
            logger.info("输入文件信息", 
                       file=str(input_file),
                       exists=True,
                       size=file_size,
                       size_mb=file_size / (1024*1024),
                       readable=os.access(input_file, os.R_OK))
        else:
            logger.error("输入文件不存在", file=str(input_file))
            raise FileNotFoundError(f"输入文件不存在: {input_file}")
        
        # 检查输出目录
        logger.info("输出目录信息",
                   dir=str(output_dir),
                   exists=output_dir.exists(),
                   writable=os.access(output_dir, os.W_OK) if output_dir.exists() else False)
        
        # 检查磁盘空间
        import shutil
        total, used, free = shutil.disk_usage(str(output_dir.parent))
        logger.info("磁盘空间", 
                   total_gb=total // (1024**3),
                   used_gb=used // (1024**3),
                   free_gb=free // (1024**3))
        
        if free < 1024**3:  # 少于1GB
            logger.warning("磁盘空间不足", free_gb=free // (1024**3))
        
        # 检查GPU状态
        if self.enable_gpu:
            try:
                import torch
                logger.info("GPU状态检查",
                           cuda_available=torch.cuda.is_available(),
                           device_count=torch.cuda.device_count(),
                           current_device=torch.cuda.current_device() if torch.cuda.is_available() else None)
                
                if torch.cuda.is_available():
                    for i in range(torch.cuda.device_count()):
                        props = torch.cuda.get_device_properties(i)
                        memory_allocated = torch.cuda.memory_allocated(i)
                        memory_reserved = torch.cuda.memory_reserved(i)
                        logger.info(f"GPU {i} 详情",
                                   name=props.name,
                                   memory_total_gb=props.total_memory // (1024**3),
                                   memory_allocated_mb=memory_allocated // (1024**2),
                                   memory_reserved_mb=memory_reserved // (1024**2))
            except Exception as e:
                logger.error("GPU状态检查失败", error=str(e))
        
        # 测试MinerU Python API可用性
        try:
            from mineru.cli.common import do_parse
            logger.info("MinerU Python API验证成功")
        except ImportError as e:
            logger.error("MinerU Python API不可用", error=str(e))
            raise RuntimeError(f"MinerU Python API导入失败: {e}")

    def _upload_results(self, output_dir: Path, data_bucket: str, output_prefix: str) -> list:
        """
        上传处理结果到S3
        
        Args:
            output_dir: 输出目录
            data_bucket: 统一数据S3存储桶
            output_prefix: 输出前缀 (output/{job_id}/)
            
        Returns:
            上传的文件列表
        """
        logger.info("开始上传处理结果", 
                   output_dir=str(output_dir),
                   bucket=data_bucket,
                   prefix=output_prefix)
        
        uploaded_files = []
        
        # 首先检查输出目录是否存在文件
        all_files = list(output_dir.rglob('*'))
        file_list = [f for f in all_files if f.is_file()]
        
        logger.info("输出目录文件统计",
                   total_items=len(all_files),
                   files_count=len(file_list),
                   directories_count=len(all_files) - len(file_list))
        
        if not file_list:
            logger.warning("输出目录中没有文件可上传")
            # 列出所有项目进行调试
            for item in all_files:
                logger.info("目录项", path=str(item), is_file=item.is_file(), is_dir=item.is_dir())
            return uploaded_files
        
        # 遍历输出目录中的所有文件
        for file_path in file_list:
            # 计算相对路径
            relative_path = file_path.relative_to(output_dir)
            s3_key = f"{output_prefix}{relative_path}"
            
            try:
                file_size = file_path.stat().st_size
                logger.info("准备上传文件", 
                           local_file=str(file_path),
                           s3_key=s3_key,
                           size_bytes=file_size)
                
                # 上传到S3
                self.s3_client.upload_file(
                    str(file_path),
                    data_bucket,
                    s3_key,
                    ExtraArgs={
                        'Metadata': {
                            'job-id': output_prefix.strip('/').split('/')[-1],  # 从prefix提取job_id
                            'original-name': file_path.name.encode('ascii', 'ignore').decode('ascii'),  # 处理中文字符
                            'content-type': self._get_content_type(file_path)
                        }
                    }
                )
                
                s3_url = f"s3://{data_bucket}/{s3_key}"
                uploaded_files.append({
                    'file_name': file_path.name,
                    'file_type': file_path.suffix,
                    's3_url': s3_url,
                    'size': file_size
                })
                
                logger.info("文件上传成功", 
                           file=s3_url,
                           size_mb=file_size / (1024*1024))
                
            except Exception as e:
                logger.error("文件上传失败", 
                           file=str(file_path), 
                           s3_key=s3_key,
                           error=str(e))
                raise
        
        logger.info("所有文件上传完成", 
                   uploaded_count=len(uploaded_files),
                   total_size_mb=sum(f['size'] for f in uploaded_files) / (1024*1024))
        
        return uploaded_files
    
    def _get_content_type(self, file_path: Path) -> str:
        """根据文件扩展名获取Content-Type"""
        suffix = file_path.suffix.lower()
        content_types = {
            '.md': 'text/markdown',
            '.json': 'application/json',
            '.html': 'text/html',
            '.txt': 'text/plain',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.pdf': 'application/pdf',
            '.xml': 'application/xml'
        }
        return content_types.get(suffix, 'application/octet-stream')
