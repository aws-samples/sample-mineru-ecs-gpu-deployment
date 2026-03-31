#!/bin/bash

# MinerU ECS Cross-Account Deployment Script
# This script supports deployment across different AWS accounts with account-specific configurations

set -e

# Default configuration
PROJECT_NAME="mineru-ecs"
ENVIRONMENT="production"
AWS_REGION="us-east-1"
CONFIG_FILE="config.yaml"
AWS_PROFILE=""

# Template files with unified naming
INFRA_TEMPLATE="01-ecs-infrastructure.yaml"
DATA_TEMPLATE="02-ecs-data-services.yaml"
TRIGGER_TEMPLATE="03-ecs-trigger-services.yaml"
COMPUTE_TEMPLATE="04-ecs-compute-services.yaml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to get AWS account ID
get_account_id() {
    if [ -n "$AWS_PROFILE" ]; then
        aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text
    else
        aws sts get-caller-identity --query Account --output text
    fi
}

# Function to get configuration value from YAML (improved parser with comment handling)
get_config_value() {
    local key=$1
    local account_id=$2
    local env=$3
    
    if [ ! -f "$CONFIG_FILE" ]; then
        return
    fi
    
    # Try account-specific config first
    if [ -n "$account_id" ]; then
        local value=$(sed -n "/^accounts:/,/^[a-z]/p" "$CONFIG_FILE" | sed -n "/\"$account_id\":/,/^  [a-zA-Z]/p" | grep "^    $key:" | head -1 | cut -d':' -f2- | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*#.*$//' | sed 's/[[:space:]]*$//')
        if [ -n "$value" ]; then
            echo "$value"
            return
        fi
    fi
    
    # Try environment-specific config
    if [ -n "$env" ]; then
        local value=$(sed -n "/^$env:/,/^[a-z]/p" "$CONFIG_FILE" | grep "^  $key:" | head -1 | cut -d':' -f2- | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*#.*$//' | sed 's/[[:space:]]*$//')
        if [ -n "$value" ]; then
            echo "$value"
            return
        fi
    fi
    
    # Try default config
    local value=$(sed -n "/^default:/,/^[a-z]/p" "$CONFIG_FILE" | grep "^  $key:" | head -1 | cut -d':' -f2- | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*#.*$//' | sed 's/[[:space:]]*$//')
    if [ -n "$value" ]; then
        echo "$value"
        return
    fi
}

# Function to load configuration
load_config() {
    local account_id=$1
    
    print_status "Loading configuration for account: $account_id"
    
    # Load account-specific or environment-specific configurations
    local config_project_name=$(get_config_value "project_name" "$account_id" "$ENVIRONMENT")
    local config_environment=$(get_config_value "environment" "$account_id" "$ENVIRONMENT")
    local config_region=$(get_config_value "aws_region" "$account_id" "$ENVIRONMENT")
    
    # Override defaults if config values exist
    if [ -n "$config_project_name" ]; then
        PROJECT_NAME="$config_project_name"
    fi
    if [ -n "$config_environment" ]; then
        ENVIRONMENT="$config_environment"
    fi
    if [ -n "$config_region" ]; then
        AWS_REGION="$config_region"
    fi
    
    print_status "Configuration loaded:"
    print_status "  Project Name: $PROJECT_NAME"
    print_status "  Environment: $ENVIRONMENT"
    print_status "  Region: $AWS_REGION"
}

# Function to build parameters from config
build_parameters() {
    local account_id=$1
    local params=""
    
    # Basic parameters
    params="ProjectName=$PROJECT_NAME Environment=$ENVIRONMENT"
    
    # ECS parameters
    local instance_type=$(get_config_value "instance_type" "$account_id" "$ENVIRONMENT")
    local min_size=$(get_config_value "min_size" "$account_id" "$ENVIRONMENT")
    local max_size=$(get_config_value "max_size" "$account_id" "$ENVIRONMENT")
    local desired_capacity=$(get_config_value "desired_capacity" "$account_id" "$ENVIRONMENT")
    local volume_size=$(get_config_value "volume_size" "$account_id" "$ENVIRONMENT")
    
    if [ -n "$instance_type" ]; then
        params="$params InstanceType=$instance_type"
    fi
    if [ -n "$min_size" ]; then
        params="$params MinSize=$min_size"
    fi
    if [ -n "$max_size" ]; then
        params="$params MaxSize=$max_size"
    fi
    if [ -n "$desired_capacity" ]; then
        params="$params DesiredCapacity=$desired_capacity"
    fi
    if [ -n "$volume_size" ]; then
        params="$params VolumeSize=$volume_size"
    fi
    
    # Task parameters
    local task_cpu=$(get_config_value "task_cpu" "$account_id" "$ENVIRONMENT")
    local task_memory=$(get_config_value "task_memory" "$account_id" "$ENVIRONMENT")
    local task_desired_count=$(get_config_value "task_desired_count" "$account_id" "$ENVIRONMENT")
    local startup_mode=$(get_config_value "startup_mode" "$account_id" "$ENVIRONMENT")
    local container_image=$(get_config_value "container_image" "$account_id" "$ENVIRONMENT")
    local log_retention=$(get_config_value "log_retention_days" "$account_id" "$ENVIRONMENT")
    local use_gpu=$(get_config_value "use_gpu" "$account_id" "$ENVIRONMENT")
    
    # Determine GPU usage based on instance type if not explicitly set
    if [ -z "$use_gpu" ]; then
        if [[ "$instance_type" == g4dn* ]]; then
            use_gpu="true"
        else
            use_gpu="false"
        fi
    fi
    
    if [ -n "$task_cpu" ]; then
        params="$params TaskCpu=$task_cpu"
    fi
    if [ -n "$task_memory" ]; then
        params="$params TaskMemory=$task_memory"
    fi
    if [ -n "$task_desired_count" ]; then
        params="$params DesiredCount=$task_desired_count"
    fi
    if [ -n "$startup_mode" ]; then
        params="$params StartupMode=$startup_mode"
    fi
    if [ -n "$container_image" ]; then
        params="$params ContainerImage=$container_image"
    fi
    if [ -n "$log_retention" ]; then
        params="$params LogRetentionDays=$log_retention"
    fi
    if [ -n "$use_gpu" ]; then
        params="$params UseGPUResources=$use_gpu"
    fi
    
    # Debug mode parameters
    local debug_mode=$(get_config_value "debug_mode" "$account_id" "$ENVIRONMENT")
    local disable_rollback=$(get_config_value "disable_rollback" "$account_id" "$ENVIRONMENT")
    
    if [ -n "$debug_mode" ]; then
        params="$params DebugMode=$debug_mode"
    fi
    if [ -n "$disable_rollback" ]; then
        params="$params DisableRollback=$disable_rollback"
    fi
    
    # Note: ContainerImage parameter is already added above in the task parameters section
    
    echo "$params"
}

# Function to check if stack exists
stack_exists() {
    local stack_name=$1
    local aws_cmd="aws cloudformation describe-stacks --stack-name $stack_name --region $AWS_REGION"
    
    if [ -n "$AWS_PROFILE" ]; then
        aws_cmd="$aws_cmd --profile $AWS_PROFILE"
    fi
    
    $aws_cmd >/dev/null 2>&1
}

# Function to wait for stack deletion
wait_for_stack_deletion() {
    local stack_name=$1
    local max_attempts=30
    local attempt=1
    local wait_time=10
    
    print_status "Waiting for stack $stack_name to be deleted..."
    
    while [ $attempt -le $max_attempts ]; do
        if ! stack_exists "$stack_name"; then
            print_success "Stack $stack_name has been deleted"
            return 0
        fi
        
        print_status "Attempt $attempt/$max_attempts: Stack $stack_name is still being deleted, waiting ${wait_time}s..."
        sleep $wait_time
        attempt=$((attempt + 1))
    done
    
    print_error "Timed out waiting for stack $stack_name to be deleted"
    return 1
}

# Function to deploy a stack
deploy_stack() {
    local template_file=$1
    local stack_name=$2
    local parameters=$3
    
    print_status "Deploying stack: $stack_name"
    print_status "Template: $template_file"
    print_status "Parameters: $parameters"
    
    if [ ! -f "$template_file" ]; then
        print_error "Template file not found: $template_file"
        exit 1
    fi
    
    local cmd="aws cloudformation deploy \
        --template-file $template_file \
        --stack-name $stack_name \
        --region $AWS_REGION \
        --capabilities CAPABILITY_NAMED_IAM \
        --no-fail-on-empty-changeset"
    
    if [ -n "$AWS_PROFILE" ]; then
        cmd="$cmd --profile $AWS_PROFILE"
    fi
    
    if [ -n "$parameters" ]; then
        cmd="$cmd --parameter-overrides $parameters"
    fi
    
    eval $cmd
    
    if [ $? -eq 0 ]; then
        print_success "Stack $stack_name deployed successfully"
    else
        print_error "Failed to deploy stack $stack_name"
        exit 1
    fi
}

# Function to validate prerequisites
validate_prerequisites() {
    print_status "Validating prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed"
        exit 1
    fi
    
    # Check AWS credentials
    local test_cmd="aws sts get-caller-identity"
    if [ -n "$AWS_PROFILE" ]; then
        test_cmd="$test_cmd --profile $AWS_PROFILE"
    fi
    
    if ! $test_cmd >/dev/null 2>&1; then
        print_error "AWS credentials not configured or invalid"
        if [ -n "$AWS_PROFILE" ]; then
            print_error "Profile: $AWS_PROFILE"
        fi
        exit 1
    fi
    
    # Check required template files
    local required_files=("$INFRA_TEMPLATE" "$DATA_TEMPLATE" "$TRIGGER_TEMPLATE" "$COMPUTE_TEMPLATE")
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            print_error "Required template file not found: $file"
            exit 1
        fi
    done
    
    print_success "Prerequisites validated"
}

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS] COMMAND"
    echo ""
    echo "Commands:"
    echo "  deploy-all      Deploy all stacks in order"
    echo "  deploy-infra    Deploy infrastructure stack only"
    echo "  deploy-data     Deploy data services stack only"
    echo "  deploy-trigger  Deploy trigger services stack only"
    echo "  deploy-compute  Deploy compute services stack only"
    echo "  delete-all      Complete cleanup: empty S3, delete stacks, remove logs"
    echo "  status          Show status of all stacks"
    echo "  validate        Validate configuration and prerequisites"
    echo ""
    echo "Options:"
    echo "  -p, --project   Project name (overrides config)"
    echo "  -e, --env       Environment (overrides config)"
    echo "  -r, --region    AWS region (overrides config)"
    echo "  -c, --config    Configuration file (default: config.yaml)"
    echo "  --profile       AWS profile to use"
    echo "  -h, --help      Show this help message"
    echo ""
    echo "Template files:"
    echo "  Infrastructure: $INFRA_TEMPLATE"
    echo "  Data Services:  $DATA_TEMPLATE"
    echo "  Trigger Services: $TRIGGER_TEMPLATE"
    echo "  Compute Services: $COMPUTE_TEMPLATE"
    echo ""
    echo "Configuration:"
    echo "  The script reads from $CONFIG_FILE and supports:"
    echo "  - Environment-specific settings (development, staging, production)"
    echo "  - Account-specific overrides"
    echo ""
    echo "Examples:"
    echo "  # Deploy to current account with default config"
    echo "  $0 deploy-all"
    echo ""
    echo "  # Deploy to specific account with profile"
    echo "  $0 --profile prod-account deploy-all"
    echo ""
    echo "  # Deploy with custom environment"
    echo "  $0 -e staging deploy-all"
    echo ""
    echo "  # Complete cleanup (removes all resources)"
    echo "  $0 delete-all"
    echo ""
    echo "  # Check deployment status"
    echo "  $0 status"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--project)
            PROJECT_NAME="$2"
            shift 2
            ;;
        -e|--env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -r|--region)
            AWS_REGION="$2"
            shift 2
            ;;
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --profile)
            AWS_PROFILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        deploy-all|deploy-infra|deploy-data|deploy-trigger|deploy-compute|delete-all|status|validate)
            COMMAND="$1"
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Check if command is provided
if [ -z "$COMMAND" ]; then
    print_error "No command provided"
    usage
    exit 1
fi

# Validate prerequisites
validate_prerequisites

# Get current AWS account ID
ACCOUNT_ID=$(get_account_id)
print_status "Current AWS Account ID: $ACCOUNT_ID"

# Load configuration
load_config "$ACCOUNT_ID"

# Update stack names with project name and environment
INFRA_STACK_NAME="${PROJECT_NAME}-infrastructure-${ENVIRONMENT}"
DATA_STACK_NAME="${PROJECT_NAME}-data-services-${ENVIRONMENT}"
TRIGGER_STACK_NAME="${PROJECT_NAME}-trigger-services-${ENVIRONMENT}"
COMPUTE_STACK_NAME="${PROJECT_NAME}-compute-services-${ENVIRONMENT}"

# Build parameters
INFRA_PARAMS=$(build_parameters "$ACCOUNT_ID")
DATA_PARAMS="ProjectName=$PROJECT_NAME Environment=$ENVIRONMENT"
TRIGGER_PARAMS="ProjectName=$PROJECT_NAME Environment=$ENVIRONMENT DataStackName=$DATA_STACK_NAME InfraStackName=$INFRA_STACK_NAME"
COMPUTE_PARAMS=$(build_parameters "$ACCOUNT_ID")
COMPUTE_PARAMS="$COMPUTE_PARAMS DataStackName=$DATA_STACK_NAME InfraStackName=$INFRA_STACK_NAME"

# Execute command
case $COMMAND in
    validate)
        print_success "Configuration and prerequisites are valid"
        print_status "Account ID: $ACCOUNT_ID"
        print_status "Project: $PROJECT_NAME"
        print_status "Environment: $ENVIRONMENT"
        print_status "Region: $AWS_REGION"
        if [ -n "$AWS_PROFILE" ]; then
            print_status "AWS Profile: $AWS_PROFILE"
        fi
        print_status "Template Files:"
        echo "  Infrastructure: $INFRA_TEMPLATE"
        echo "  Data Services:  $DATA_TEMPLATE"
        echo "  Trigger Services: $TRIGGER_TEMPLATE"
        echo "  Compute Services: $COMPUTE_TEMPLATE"
        
        print_status "Configuration Values:"
        echo "  Instance Type: $(get_config_value "instance_type" "$ACCOUNT_ID" "$ENVIRONMENT")"
        echo "  Min Size: $(get_config_value "min_size" "$ACCOUNT_ID" "$ENVIRONMENT")"
        echo "  Max Size: $(get_config_value "max_size" "$ACCOUNT_ID" "$ENVIRONMENT")"
        echo "  Desired Capacity: $(get_config_value "desired_capacity" "$ACCOUNT_ID" "$ENVIRONMENT")"
        echo "  Container Image: $(get_config_value "container_image" "$ACCOUNT_ID" "$ENVIRONMENT")"
        
        print_status "Stack Names:"
        echo "  Infrastructure: $INFRA_STACK_NAME"
        echo "  Data Services: $DATA_STACK_NAME"
        echo "  Trigger Services: $TRIGGER_STACK_NAME"
        echo "  Compute Services: $COMPUTE_STACK_NAME"
        
        print_status "Infrastructure Parameters:"
        echo "  $INFRA_PARAMS"
        ;;
        
    deploy-all)
        print_status "Starting full deployment of MinerU ECS infrastructure"
        print_status "Account: $ACCOUNT_ID"
        print_status "Project: $PROJECT_NAME"
        print_status "Environment: $ENVIRONMENT"
        print_status "Region: $AWS_REGION"
        echo ""
        
        # 检查堆栈状态，如果是ROLLBACK_COMPLETE，则删除并等待删除完成
        for stack in "$INFRA_STACK_NAME" "$DATA_STACK_NAME" "$TRIGGER_STACK_NAME" "$COMPUTE_STACK_NAME"; do
            if stack_exists "$stack"; then
                stack_status_cmd="aws cloudformation describe-stacks --stack-name $stack --region $AWS_REGION --query 'Stacks[0].StackStatus' --output text"
                if [ -n "$AWS_PROFILE" ]; then
                    stack_status_cmd="$stack_status_cmd --profile $AWS_PROFILE"
                fi
                stack_status=$(eval $stack_status_cmd 2>/dev/null || echo "DOES_NOT_EXIST")
                
                if [ "$stack_status" = "ROLLBACK_COMPLETE" ]; then
                    print_warning "Stack $stack is in ROLLBACK_COMPLETE state and needs to be deleted before deployment"
                    
                    delete_cmd="aws cloudformation delete-stack --stack-name $stack --region $AWS_REGION"
                    if [ -n "$AWS_PROFILE" ]; then
                        delete_cmd="$delete_cmd --profile $AWS_PROFILE"
                    fi
                    
                    print_status "Deleting stack: $stack"
                    eval $delete_cmd
                    
                    # 等待堆栈删除完成
                    wait_for_stack_deletion "$stack"
                fi
            fi
        done
        
        # Deploy all stacks in order
        deploy_stack "$INFRA_TEMPLATE" "$INFRA_STACK_NAME" "$INFRA_PARAMS"
        deploy_stack "$DATA_TEMPLATE" "$DATA_STACK_NAME" "$DATA_PARAMS"
        deploy_stack "$TRIGGER_TEMPLATE" "$TRIGGER_STACK_NAME" "$TRIGGER_PARAMS"
        deploy_stack "$COMPUTE_TEMPLATE" "$COMPUTE_STACK_NAME" "$COMPUTE_PARAMS"
        
        # 创建S3存储桶文件夹结构
        print_status "Creating S3 bucket folder structure..."
        
        # 获取数据存储桶名称
        bucket_name_cmd="aws cloudformation describe-stacks --stack-name $DATA_STACK_NAME --region $AWS_REGION --query \"Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue\" --output text"
        if [ -n "$AWS_PROFILE" ]; then
            bucket_name_cmd="$bucket_name_cmd --profile $AWS_PROFILE"
        fi
        
        BUCKET_NAME=$(eval $bucket_name_cmd)
        
        if [ -n "$BUCKET_NAME" ]; then
            print_status "Creating folders in bucket: $BUCKET_NAME"
            
            # 创建input文件夹
            input_cmd="aws s3api put-object --bucket $BUCKET_NAME --key input/ --content-length 0"
            if [ -n "$AWS_PROFILE" ]; then
                input_cmd="$input_cmd --profile $AWS_PROFILE"
            fi
            eval $input_cmd
            
            # 创建processed文件夹
            processed_cmd="aws s3api put-object --bucket $BUCKET_NAME --key processed/ --content-length 0"
            if [ -n "$AWS_PROFILE" ]; then
                processed_cmd="$processed_cmd --profile $AWS_PROFILE"
            fi
            eval $processed_cmd
            
            print_success "S3 folder structure created successfully!"
        else
            print_warning "Could not retrieve bucket name. Please create folders manually."
        fi
        
        print_success "Full deployment completed successfully!"
        ;;
        
    deploy-infra)
        deploy_stack "$INFRA_TEMPLATE" "$INFRA_STACK_NAME" "$INFRA_PARAMS"
        ;;
        
    deploy-data)
        deploy_stack "$DATA_TEMPLATE" "$DATA_STACK_NAME" "$DATA_PARAMS"
        ;;
        
    deploy-trigger)
        if ! stack_exists "$INFRA_STACK_NAME" || ! stack_exists "$DATA_STACK_NAME"; then
            print_error "Infrastructure and data services stacks must be deployed first"
            exit 1
        fi
        deploy_stack "$TRIGGER_TEMPLATE" "$TRIGGER_STACK_NAME" "$TRIGGER_PARAMS"
        ;;
        
    deploy-compute)
        if ! stack_exists "$INFRA_STACK_NAME" || ! stack_exists "$DATA_STACK_NAME"; then
            print_error "Infrastructure and data services stacks must be deployed first"
            exit 1
        fi
        deploy_stack "$COMPUTE_TEMPLATE" "$COMPUTE_STACK_NAME" "$COMPUTE_PARAMS"
        ;;
        
    delete-all)
        print_warning "This will delete ALL stacks and resources. Are you sure? (y/N)"
        read -r confirmation
        if [[ $confirmation =~ ^[Yy]$ ]]; then
            print_status "Starting complete cleanup process..."
            
            # Step 1: Get bucket name before deleting stacks
            print_status "Step 1: Retrieving S3 bucket name..."
            if stack_exists "$DATA_STACK_NAME"; then
                bucket_name_cmd="aws cloudformation describe-stacks --stack-name $DATA_STACK_NAME --region $AWS_REGION --query \"Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue\" --output text"
                if [ -n "$AWS_PROFILE" ]; then
                    bucket_name_cmd="$bucket_name_cmd --profile $AWS_PROFILE"
                fi
                BUCKET_NAME=$(eval $bucket_name_cmd 2>/dev/null || echo "")
                
                if [ -n "$BUCKET_NAME" ]; then
                    print_status "Found bucket: $BUCKET_NAME"
                    
                    # Empty S3 bucket
                    print_status "Emptying S3 bucket..."
                    empty_cmd="aws s3 rm s3://$BUCKET_NAME --recursive --region $AWS_REGION"
                    if [ -n "$AWS_PROFILE" ]; then
                        empty_cmd="$empty_cmd --profile $AWS_PROFILE"
                    fi
                    
                    if eval $empty_cmd; then
                        print_success "S3 bucket emptied successfully"
                    else
                        print_warning "Failed to empty S3 bucket, continuing with stack deletion..."
                    fi
                else
                    print_warning "Could not retrieve bucket name, skipping S3 cleanup"
                fi
            fi
            
            # Step 2: Delete stacks in reverse order
            print_status "Step 2: Deleting CloudFormation stacks in reverse order..."
            for stack in "$COMPUTE_STACK_NAME" "$TRIGGER_STACK_NAME" "$DATA_STACK_NAME" "$INFRA_STACK_NAME"; do
                if stack_exists "$stack"; then
                    print_status "Deleting stack: $stack"
                    delete_cmd="aws cloudformation delete-stack --stack-name $stack --region $AWS_REGION"
                    if [ -n "$AWS_PROFILE" ]; then
                        delete_cmd="$delete_cmd --profile $AWS_PROFILE"
                    fi
                    eval $delete_cmd
                    
                    # Wait for stack deletion to complete
                    wait_for_stack_deletion "$stack"
                fi
            done
            
            # Step 3: Clean up remaining resources
            print_status "Step 3: Cleaning up remaining resources..."
            
            # Delete ECR repository if exists
            ecr_repo_name="${PROJECT_NAME}-processor"
            print_status "Checking for ECR repository: $ecr_repo_name"
            ecr_check_cmd="aws ecr describe-repositories --repository-names $ecr_repo_name --region $AWS_REGION"
            if [ -n "$AWS_PROFILE" ]; then
                ecr_check_cmd="$ecr_check_cmd --profile $AWS_PROFILE"
            fi
            
            if eval $ecr_check_cmd >/dev/null 2>&1; then
                print_status "Deleting ECR repository: $ecr_repo_name"
                ecr_delete_cmd="aws ecr delete-repository --repository-name $ecr_repo_name --force --region $AWS_REGION"
                if [ -n "$AWS_PROFILE" ]; then
                    ecr_delete_cmd="$ecr_delete_cmd --profile $AWS_PROFILE"
                fi
                eval $ecr_delete_cmd
            fi
            
            # Delete CloudWatch log groups
            print_status "Deleting CloudWatch log groups..."
            for log_group in "/ecs/${PROJECT_NAME}-processor" "/aws/lambda/${PROJECT_NAME}-trigger" "/aws/lambda/${PROJECT_NAME}-postprocess"; do
                log_check_cmd="aws logs describe-log-groups --log-group-name-prefix $log_group --region $AWS_REGION"
                if [ -n "$AWS_PROFILE" ]; then
                    log_check_cmd="$log_check_cmd --profile $AWS_PROFILE"
                fi
                
                if eval $log_check_cmd >/dev/null 2>&1; then
                    print_status "Deleting log group: $log_group"
                    log_delete_cmd="aws logs delete-log-group --log-group-name $log_group --region $AWS_REGION"
                    if [ -n "$AWS_PROFILE" ]; then
                        log_delete_cmd="$log_delete_cmd --profile $AWS_PROFILE"
                    fi
                    eval $log_delete_cmd 2>/dev/null || true
                fi
            done
            
            # Step 4: Verify cleanup
            print_status "Step 4: Verifying cleanup..."
            remaining_stacks_cmd="aws cloudformation list-stacks --region $AWS_REGION --query \"StackSummaries[?contains(StackName, '$PROJECT_NAME') && StackStatus != 'DELETE_COMPLETE'].StackName\" --output text"
            if [ -n "$AWS_PROFILE" ]; then
                remaining_stacks_cmd="$remaining_stacks_cmd --profile $AWS_PROFILE"
            fi
            
            remaining_stacks=$(eval $remaining_stacks_cmd)
            if [ -z "$remaining_stacks" ]; then
                print_success "All stacks deleted successfully!"
            else
                print_warning "Some stacks may still exist: $remaining_stacks"
            fi
            
            print_success "Complete cleanup finished!"
            print_status "Summary:"
            echo "  ✓ S3 bucket emptied"
            echo "  ✓ CloudFormation stacks deleted"
            echo "  ✓ ECR repository cleaned"
            echo "  ✓ CloudWatch logs removed"
        else
            print_status "Deletion cancelled"
        fi
        ;;
        
    status)
        print_status "Stack Status Summary for Account: $ACCOUNT_ID"
        echo ""
        
        for stack in "$INFRA_STACK_NAME" "$DATA_STACK_NAME" "$TRIGGER_STACK_NAME" "$COMPUTE_STACK_NAME"; do
            if stack_exists "$stack"; then
                status_cmd="aws cloudformation describe-stacks --stack-name $stack --region $AWS_REGION --query 'Stacks[0].StackStatus' --output text"
                if [ -n "$AWS_PROFILE" ]; then
                    status_cmd="$status_cmd --profile $AWS_PROFILE"
                fi
                status=$(eval $status_cmd)
                
                case $status in
                    *COMPLETE)
                        print_success "$stack: $status"
                        ;;
                    *PROGRESS)
                        print_warning "$stack: $status"
                        ;;
                    *FAILED)
                        print_error "$stack: $status"
                        ;;
                    *)
                        echo "$stack: $status"
                        ;;
                esac
            else
                echo "$stack: NOT_DEPLOYED"
            fi
        done
        ;;
        
    *)
        print_error "Unknown command: $COMMAND"
        usage
        exit 1
        ;;
esac
