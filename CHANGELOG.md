# Changelog

All notable changes to this sample project will be documented in this file.

## [2.0.0] - 2026-03-30

### Breaking Changes
- Upgraded MinerU from 2.1.0 to 3.0.1
- Docker base image changed from `pytorch/pytorch:2.7.1` to `vllm/vllm-openai:v0.11.2`
- Default parsing backend changed from `unimernet` to `hybrid-auto-engine`
- ECS AMI migrated from Amazon Linux 2 (EOL June 2026) to Amazon Linux 2023
- Processor now uses MinerU Python API (`do_parse()`) instead of CLI subprocess

### Added
- MinerU v3 hybrid-auto-engine support with 1.2B VLM model (90+ accuracy on OmniDocBench)
- vLLM inference engine for GPU-accelerated VLM processing
- Dynamic AL2023 AMI resolution via SSM Parameter Store
- IMDSv2 support in UserData (AL2023 default)
- `MINERU_MODEL_SOURCE`, `MINERU_BACKEND`, `MINERU_DEVICE_MODE` environment variables in ECS task definition
- Test suite for AL2023 migration validation (20 tests)
- Test suite for MinerU v3 compatibility validation (23 tests)

### Changed
- `processor.py`: Replaced subprocess CLI call with direct `do_parse()` Python API — eliminates HTTP timeout issues on first vLLM initialization
- `Dockerfile.ecs-gpu`: Rebuilt on vllm base image, installs `mineru[core]>=3.0.0`, pre-downloads all models
- `entrypoint.sh`: Simplified for MinerU v3, removed legacy `fix-cuda.sh` references
- `health_checker.py`: Updated MinerU import paths for v3
- `01-ecs-infrastructure.yaml`: Removed hardcoded AMI Mappings, uses SSM dynamic references for AL2023 GPU/standard AMIs
- `04-ecs-compute-services.yaml`: Fixed BUCKET_NAME mismatch bug, added MinerU v3 env vars, increased TaskMemory default to 12288MB and TaskCpu to 3072
- `deploy-cross-account.sh`: Changed from `aws cloudformation deploy` (changeset) to `create-stack`/`update-stack` (direct) to avoid EarlyValidation issues
- `config.yaml`: Increased `volume_size` to 200GB for 35GB Docker image
- `docker-compose.yml`: Updated environment variables for MinerU v3

### Fixed
- S3 bucket `ResourceExistenceCheck` failure when redeploying with `cloudformation deploy`
- `BUCKET_NAME` env var in ECS task had extra `${AWS::Region}` suffix not matching actual S3 bucket name
- `yum install -y awscli` in UserData fails on AL2023 (AWS CLI v2 is pre-installed)
- IMDSv1 metadata calls in debug mode fail on AL2023 (defaults to IMDSv2)
- `HealthCheckGracePeriodSeconds` too short (300s) for 35GB image pull — increased to 900s
- `blinker` package conflict when installing Flask on vllm base image — added `--ignore-installed`
- NumPy 2.4 incompatibility with numba (vllm dependency) — pinned `numpy<2.3`

### Removed
- Hardcoded AL2 AMI ID mappings (12 regions × 2 types)
- `FindInMap` references for AMI selection
- `subprocess` dependency in processor.py
- Legacy `unimernet` backend reference
- `/opt/MinerU` source path fallback in health checker and entrypoint

## [1.0.0] - 2025-11-27

### Added
- Initial release of MinerU ECS GPU deployment sample
- CloudFormation templates for infrastructure deployment
- ECS task definitions with GPU support (g4dn.xlarge)
- S3 event-driven processing pipeline
- DynamoDB job tracking
- CloudFront CDN integration for processed content
- Auto-scaling configuration (0-10 instances)
- Comprehensive deployment documentation
- Cost optimization examples
- Multi-account deployment support

### Features
- GPU-accelerated PDF processing using MinerU 2.1.0
- Serverless architecture with automatic scaling
- Event-driven workflow (S3 → SQS → ECS)
- CloudWatch monitoring and alerting
- Cross-account deployment scripts
- Docker containerization with CUDA support

### Documentation
- Complete README with architecture diagrams
- Deployment guide with step-by-step instructions
- Troubleshooting section
- Cost analysis and optimization tips
- Security best practices
