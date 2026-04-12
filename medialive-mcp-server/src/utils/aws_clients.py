"""AWS client singletons for performance optimization"""
import boto3
from typing import Dict, Any

class AWSClientManager:
    """Singleton manager for AWS clients"""
    _instance = None
    _clients: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_client(self, service_name: str, **kwargs):
        """Get or create AWS client"""
        key = f"{service_name}_{hash(frozenset(kwargs.items()))}"
        if key not in self._clients:
            self._clients[key] = boto3.client(service_name, **kwargs)
        return self._clients[key]

# Global instance
aws_clients = AWSClientManager()
