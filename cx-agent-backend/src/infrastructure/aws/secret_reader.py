import boto3

from domain.ports.secret_reader import SecretReader
from infrastructure.config.settings import settings

class AWSSecretsReader(SecretReader):
    def read_secret(self, name: str) -> str:
        client = boto3.client("secretsmanager", region_name=settings.aws_region)
        try:
            response = client.get_secret_value(SecretId=name)
            return response["SecretString"]
        except client.exceptions.ResourceNotFoundException:
            raise ValueError(f"Missing secret value for {name}")
