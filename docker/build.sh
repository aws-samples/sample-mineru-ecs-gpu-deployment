#!/bin/bash

# MinerU ECS Docker Build Script
# This script builds and optionally pushes the MinerU Docker image

set -e

# Configuration
DEFAULT_IMAGE_NAME="mineru-ecs"
DEFAULT_TAG="latest"
DEFAULT_REGISTRY=""
DOCKERFILE="Dockerfile.ecs-gpu"

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

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -n, --name          Image name (default: $DEFAULT_IMAGE_NAME)"
    echo "  -t, --tag           Image tag (default: $DEFAULT_TAG)"
    echo "  -r, --registry      Docker registry URL (optional)"
    echo "  -f, --dockerfile    Dockerfile name (default: $DOCKERFILE)"
    echo "  -p, --push          Push image to registry after build"
    echo "  --no-cache          Build without using cache"
    echo "  --platform          Target platform (e.g., linux/amd64)"
    echo "  --build-arg         Build argument (can be used multiple times)"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  # Basic build"
    echo "  $0"
    echo ""
    echo "  # Build with custom name and tag"
    echo "  $0 -n my-mineru -t v1.0.0"
    echo ""
    echo "  # Build and push to ECR"
    echo "  $0 -r YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com -p"
    echo ""
    echo "  # Build with build arguments"
    echo "  $0 --build-arg MINERU_VERSION=1.2.0 --build-arg CUDA_VERSION=12.1"
}

# Parse command line arguments
IMAGE_NAME="$DEFAULT_IMAGE_NAME"
TAG="$DEFAULT_TAG"
REGISTRY="$DEFAULT_REGISTRY"
PUSH=false
NO_CACHE=false
PLATFORM=""
BUILD_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--name)
            IMAGE_NAME="$2"
            shift 2
            ;;
        -t|--tag)
            TAG="$2"
            shift 2
            ;;
        -r|--registry)
            REGISTRY="$2"
            shift 2
            ;;
        -f|--dockerfile)
            DOCKERFILE="$2"
            shift 2
            ;;
        -p|--push)
            PUSH=true
            shift
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --platform)
            PLATFORM="$2"
            shift 2
            ;;
        --build-arg)
            BUILD_ARGS+=("--build-arg" "$2")
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate prerequisites
print_status "Validating prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed or not in PATH"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info >/dev/null 2>&1; then
    print_error "Docker daemon is not running"
    exit 1
fi

# Check if Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
    print_error "Dockerfile not found: $DOCKERFILE"
    exit 1
fi

print_success "Prerequisites validated"

# Build image name
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}:${TAG}"
else
    FULL_IMAGE_NAME="${IMAGE_NAME}:${TAG}"
fi

print_status "Building Docker image..."
print_status "Image name: $FULL_IMAGE_NAME"
print_status "Dockerfile: $DOCKERFILE"

# Build Docker command
BUILD_CMD="docker build"

# Add build arguments
if [ ${#BUILD_ARGS[@]} -gt 0 ]; then
    BUILD_CMD="$BUILD_CMD ${BUILD_ARGS[*]}"
fi

# Add no-cache flag
if [ "$NO_CACHE" = true ]; then
    BUILD_CMD="$BUILD_CMD --no-cache"
fi

# Add platform flag
if [ -n "$PLATFORM" ]; then
    BUILD_CMD="$BUILD_CMD --platform $PLATFORM"
fi

# Add dockerfile and tag
BUILD_CMD="$BUILD_CMD -f $DOCKERFILE -t $FULL_IMAGE_NAME ."

print_status "Build command: $BUILD_CMD"

# Execute build
if eval $BUILD_CMD; then
    print_success "Docker image built successfully: $FULL_IMAGE_NAME"
else
    print_error "Docker build failed"
    exit 1
fi

# Get image size
IMAGE_SIZE=$(docker images --format "table {{.Size}}" "$FULL_IMAGE_NAME" | tail -n 1)
print_status "Image size: $IMAGE_SIZE"

# Push image if requested
if [ "$PUSH" = true ]; then
    if [ -z "$REGISTRY" ]; then
        print_error "Registry URL is required for push operation"
        exit 1
    fi
    
    print_status "Pushing image to registry..."
    
    # Check if we need to login to ECR
    if [[ "$REGISTRY" == *".ecr."* ]]; then
        print_status "Detected ECR registry, attempting login..."
        
        # Extract region from ECR URL
        REGION=$(echo "$REGISTRY" | cut -d'.' -f4)
        
        # Login to ECR
        if aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"; then
            print_success "ECR login successful"
        else
            print_error "ECR login failed"
            exit 1
        fi
    fi
    
    # Push image
    if docker push "$FULL_IMAGE_NAME"; then
        print_success "Image pushed successfully: $FULL_IMAGE_NAME"
    else
        print_error "Image push failed"
        exit 1
    fi
fi

# Display summary
print_success "Build completed successfully!"
echo ""
print_status "=== Build Summary ==="
echo "Image Name: $FULL_IMAGE_NAME"
echo "Image Size: $IMAGE_SIZE"
echo "Dockerfile: $DOCKERFILE"
if [ "$PUSH" = true ]; then
    echo "Registry: $REGISTRY"
    echo "Pushed: Yes"
else
    echo "Pushed: No"
fi

# Show next steps
echo ""
print_status "=== Next Steps ==="
echo "1. Test the image locally:"
echo "   docker run --rm -it $FULL_IMAGE_NAME"
echo ""
echo "2. Run with GPU support (if available):"
echo "   docker run --rm -it --gpus all $FULL_IMAGE_NAME"
echo ""
if [ "$PUSH" = false ] && [ -n "$REGISTRY" ]; then
    echo "3. Push to registry:"
    echo "   $0 -r $REGISTRY -p"
    echo ""
fi
echo "4. Update CloudFormation template with new image:"
echo "   ContainerImage: $FULL_IMAGE_NAME"
