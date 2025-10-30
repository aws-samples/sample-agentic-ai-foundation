
***NOTE: Deploying the LLM Gateway and Langfuse platform would be needed to incorporate centralized model management and observability.***


Before we get started, we would need to deploy the following:
- A Generative AI Gateway to be able to invoke multi-provider models
- An observability platform with Langfuse to collect and analyze detailed telemetry from the agent as it runs
- Optionally retrieve web search and support ticket API keys
- A knowledge base with the help of [Amazon Bedrock Knowledge Base](https://aws.amazon.com/bedrock/knowledge-bases/)
- A guardrail with the help of [Amazon Bedrock Guardrails]([https://aws.amazon.com/bedrock/guardrails/](url))
- Set-up cognito authentication
- Create and store keys and secrets 


### Multi Provider Generative AI Gateway Deployment

Deploy a multi-provider gateway on AWS by referring to this [guidance](https://aws.amazon.com/solutions/guidance/multi-provider-generative-ai-gateway-on-aws/).

### Observability Platform with Langfuse

If you would like to self-host your own Langfuse platform, refer to this [guidance](https://github.com/awslabs/amazon-bedrock-agent-samples/tree/main/examples/agent_observability/deploy-langfuse-on-ecs-fargate-with-typescript-cdk). You could also use the [cloud](https://cloud.langfuse.com/auth/sign-up) version instead.

### Infrastructure Deployment

Deploy all infrastructure components using the unified Terraform stack:

```bash
# Navigate to infrastructure directory
cd infra

# Copy and customize the variables file
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars and replace placeholder values with your actual values

# Initialize and deploy all components
terraform init
terraform plan
terraform apply
```

This will deploy:
- Bedrock AgentCore IAM Role with required permissions
- Knowledge Base stack (S3 bucket, OpenSearch Serverless, Knowledge Base)
- Bedrock Guardrails for content filtering
- Cognito User Pool for authentication
- SSM Parameters for configuration
- Secrets Manager secrets for API keys

### Configuration

After deployment, the following outputs will be available:
- `bedrock_role_arn`: IAM role ARN for Bedrock agents
- `knowledge_base_id`: Knowledge base ID for document retrieval
- `data_source_id`: Data source ID for knowledge base
- `guardrail_id`: Guardrail ID for content filtering
- `user_pool_id`: Cognito user pool ID
- `client_id`: Cognito client ID
- `client_secret`: Cognito client secret (sensitive)

All configuration values are automatically stored in AWS Systems Manager Parameter Store and Secrets Manager.


**Upload your documents to the S3 bucket**:
```bash
# Use bucket name from Terraform output
aws s3 cp your-documents/ s3://$(terraform output -raw s3_bucket_name)/ --recursive
```

**Trigger knowledge base ingestion**:
```bash
# Use IDs from Terraform outputs
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id $(terraform output -raw knowledge_base_id) \
  --data-source-id $(terraform output -raw data_source_id)
```
