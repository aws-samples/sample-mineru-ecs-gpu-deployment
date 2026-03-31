# Security Policy

## Reporting a Vulnerability

If you discover a potential security issue in this project, we ask that you notify AWS Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.

## Security Best Practices

When deploying this sample code, please consider the following security best practices:

### 1. IAM Permissions
- Use least privilege IAM roles for all AWS services
- Avoid using AWS account root user credentials
- Enable MFA for IAM users with console access
- Regularly rotate access keys

### 2. Network Security
- Deploy ECS tasks in private subnets
- Use security groups to restrict network access
- Enable VPC Flow Logs for network monitoring
- Consider using AWS PrivateLink for service endpoints

### 3. Data Protection
- Enable encryption at rest for S3 buckets
- Enable encryption in transit (HTTPS/TLS)
- Use AWS KMS for encryption key management
- Implement appropriate S3 bucket policies

### 4. Monitoring and Logging
- Enable CloudTrail for API logging
- Configure CloudWatch alarms for security events
- Enable ECS container insights
- Review logs regularly for suspicious activity

### 5. Secrets Management
- Never hardcode credentials in code
- Use AWS Secrets Manager or Systems Manager Parameter Store
- Rotate secrets regularly
- Use IAM roles for service-to-service authentication

### 6. Container Security
- Regularly update base Docker images
- Scan container images for vulnerabilities
- Use minimal base images
- Run containers as non-root users when possible

## Compliance

This sample code is provided as-is for demonstration purposes. Organizations should evaluate and implement appropriate security controls based on their specific compliance requirements (e.g., HIPAA, PCI-DSS, SOC 2).

## Updates

We recommend regularly checking for updates to this sample code and the underlying dependencies, including:
- AWS service updates
- MinerU library updates
- Python package updates
- Security patches for base images
