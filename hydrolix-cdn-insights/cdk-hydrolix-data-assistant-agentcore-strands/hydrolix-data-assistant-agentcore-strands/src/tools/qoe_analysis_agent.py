"""
QoE (Quality of Experience) Analysis Subagent

This subagent specializes in streaming video Quality of Experience analysis including:
- Buffer health and starvation analysis
- Bitrate adaptation and throughput metrics
- Session-level quality tracking
- Geographic QoE breakdown
- CMCD data quality validation
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


def _load_qoe_system_prompt(user_timezone: str = "US/Pacific") -> str:
    """Load the system prompt for QoE analysis."""
    fallback_prompt = """You are a specialized Quality of Experience (QoE) Analyst with expertise in 
        analyzing streaming video quality metrics, buffer health, bitrate adaptation, and viewer experience. 
        You can execute SQL queries using ClickHouse dialect and provide actionable QoE insights."""

    try:
        # Get table name from environment variable
        hydrolix_table = os.getenv('HYDROLIX_TABLE', '')
        
        prompt = load_file_content(
            "src/tools/qoe_analysis_instructions.txt", 
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
def qoe_analysis_agent(query: str) -> str:
    """
    Analyze streaming video Quality of Experience (QoE) metrics.
    
    This subagent specializes in QoE analysis using CMCD data, including:
    - Buffer health analysis (buffer length, starvation events)
    - Bitrate adaptation (encoded bitrate, throughput, top bitrate)
    - Session-level quality tracking and startup performance
    - Geographic QoE breakdown by country and edge location
    - Content segmentation analysis by type and format
    
    IMPORTANT: CMCD fields are player-side telemetry and may have NULL values
    if the video player doesn't implement CMCD. Always validate data quality first.
    
    Args:
        query: User question about streaming video quality of experience
        
    Returns:
        str: QoE analysis results and recommendations
    """
    ctx = get_request_context()
    prompt_uuid = ctx.prompt_uuid or str(uuid4())
    user_timezone = ctx.user_timezone
    
    print(f"\n{'='*60}")
    print("📺 QoE ANALYSIS SUBAGENT")
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
            
            system_prompt = _load_qoe_system_prompt(user_timezone)
            
            agent = Agent(
                model=bedrock_model,
                system_prompt=system_prompt,
                tools=tools,
                callback_handler=None,
            )
            
            print("🚀 Processing QoE analysis...")
            print(f"{'='*60}")
            
            formatted_query = f"Analyze Quality of Experience for: {query}"
            text_response = asyncio.run(process_agent_stream(agent, formatted_query, agent_name="qoe_analysis_agent"))
            
            print(f"\n{'='*60}")
            
            if text_response:
                return text_response
            
            return "I apologize, but I couldn't process your QoE analysis request."

    except Exception as e:
        print(f"❌ Error in QoE analysis: {str(e)}")
        return f"Error processing QoE query: {str(e)}"
