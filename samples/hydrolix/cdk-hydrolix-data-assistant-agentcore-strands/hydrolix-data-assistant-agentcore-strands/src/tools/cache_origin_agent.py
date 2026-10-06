"""
Cache & Origin Performance Analysis Subagent

This subagent specializes in CDN cache efficiency and origin server performance including:
- Cache hit/miss analysis
- Origin vs edge timing comparisons
- Error rate analysis by status code
- Bandwidth and byte cost analysis
- Edge location performance breakdown
"""

import json
import os
import asyncio
import boto3
from uuid import uuid4

from strands import Agent, tool
from strands_tools import current_time, calculator
from strands.models import BedrockModel
from mcp import stdio_client, StdioServerParameters
from strands.tools.mcp import MCPClient

from src.utils import load_file_content, get_request_context, process_agent_stream


def _load_cache_origin_system_prompt(user_timezone: str = "US/Pacific") -> str:
    """Load the system prompt for cache and origin performance analysis."""
    fallback_prompt = """You are a specialized CDN Cache & Origin Performance Analyst with expertise in 
        analyzing cache efficiency, origin server performance, and content delivery optimization. 
        You can execute SQL queries using ClickHouse dialect and provide actionable CDN insights."""

    try:
        # Get table name from environment variable
        hydrolix_table = os.getenv('HYDROLIX_TABLE', '')
        
        prompt = load_file_content(
            "src/tools/cache_origin_instructions.txt", 
            default_content=fallback_prompt
        )
        # Replace both timezone and table name placeholders
        prompt = prompt.replace("{timezone}", user_timezone)
        prompt = prompt.replace("{hydrolix_table}", hydrolix_table)
        return prompt
    except Exception:
        return fallback_prompt.replace("{timezone}", user_timezone)


def _get_hydrolix_mcp_env() -> dict:
    """Get Hydrolix configuration from AWS Secrets Manager."""
    secret_arn = os.getenv('HYDROLIX_SECRET_ARN')
    if not secret_arn:
        raise ValueError("HYDROLIX_SECRET_ARN environment variable not set")
    
    secrets_region = os.getenv("AWS_REGION", "us-east-1")
    secrets_client = boto3.client('secretsmanager', region_name=secrets_region)
    
    secret_response = secrets_client.get_secret_value(SecretId=secret_arn)
    secret_data = json.loads(secret_response['SecretString'])

    return {
        "HYDROLIX_HOST": secret_data.get('HYDROLIX_HOST'),
        "HYDROLIX_PORT": secret_data.get('HYDROLIX_PORT', '8088'),
        "HYDROLIX_USER": secret_data.get('HYDROLIX_USER'),
        "HYDROLIX_PASSWORD": secret_data.get('HYDROLIX_PASSWORD'),
    }


@tool
def cache_origin_agent(query: str) -> str:
    """
    Analyze CDN cache efficiency and origin server performance.
    
    This subagent specializes in cache and origin analysis, including:
    - Cache hit/miss rates and efficiency metrics
    - Origin vs edge timing comparisons (TTFB, TTLB)
    - HTTP error rate analysis by status code
    - Bandwidth and byte cost analysis
    - Edge location (POP) performance breakdown
    - Content type caching patterns
    
    This data comes from CDN access logs directly (not player telemetry),
    so it has near-100% fill rates and high reliability.
    
    Args:
        query: User question about cache performance or origin metrics
        
    Returns:
        str: Cache and origin performance analysis results
    """
    ctx = get_request_context()
    prompt_uuid = ctx.prompt_uuid or str(uuid4())
    user_timezone = ctx.user_timezone
    
    print(f"\n{'='*60}")
    print("🗄️ CACHE & ORIGIN PERFORMANCE SUBAGENT")
    print(f"{'='*60}")
    print(f"📝 Query: {query}")
    print(f"🌍 Timezone: {user_timezone}")
    print(f"🆔 Prompt UUID: {prompt_uuid}")
    print(f"{'='*60}")
    
    try:
        mcp_env = _get_hydrolix_mcp_env()
        
        print("\n🔌 INITIALIZING HYDROLIX MCP CLIENT")
        print("="*40)
        
        hydrolix_mcp_server = MCPClient(
            lambda: stdio_client(
                StdioServerParameters(
                    command="python",
                    args=["-m", "mcp_hydrolix.main"],
                    env={
                        **mcp_env,
                        "PYTHONPATH": os.path.join(os.getcwd(), "src/mcp"),
                    }
                )
            )
        )
        
        with hydrolix_mcp_server:
            tools = hydrolix_mcp_server.list_tools_sync()
            tools.append(current_time)
            tools.append(calculator)
            
            model_id = os.getenv(
                "BEDROCK_MODEL_ID", 
                "us.anthropic.claude-sonnet-4-20250514-v1:0"
            )
            bedrock_model = BedrockModel(model_id=model_id)
            
            system_prompt = _load_cache_origin_system_prompt(user_timezone)
            
            agent = Agent(
                model=bedrock_model,
                system_prompt=system_prompt,
                tools=tools,
                callback_handler=None,
            )
            
            print("🚀 Processing cache & origin analysis...")
            print(f"{'='*60}")
            
            formatted_query = f"Analyze cache and origin performance for: {query}"
            text_response = asyncio.run(process_agent_stream(agent, formatted_query, agent_name="cache_origin_agent"))
            
            print(f"\n{'='*60}")
            
            if text_response:
                return text_response
            
            return "I apologize, but I couldn't process your cache/origin analysis request."

    except Exception as e:
        print(f"❌ Error in cache/origin analysis: {str(e)}")
        return f"Error processing cache/origin query: {str(e)}"
