"""
Hydrolix Time-Series Data Analyst Subagent

This subagent handles all Hydrolix time-series data analysis tasks including:
- SQL query generation and execution against Hydrolix using ClickHouse dialect
- Streaming video analytics and diagnostics
- Time-series data interpretation and insights
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

from src.utils import load_file_content, get_request_context


def _load_hydrolix_system_prompt(user_timezone: str = "US/Pacific") -> str:
    """Load the system prompt for Hydrolix time-series analysis."""
    fallback_prompt = """You are a specialized Hydrolix Time-Series Data Analyst with expertise in 
        analyzing streaming video analytics, CDN performance, and time-series diagnostics. You can execute SQL queries
        using ClickHouse dialect, interpret time-series data, and provide actionable insights."""

    try:
        # Get table name from environment variable
        hydrolix_table = os.getenv('HYDROLIX_TABLE', '')
        
        prompt = load_file_content(
            "src/tools/hydrolix_agent_instructions.txt", 
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
    
    print(f"🔐 Retrieving Hydrolix configuration from Secrets Manager: {secret_arn}")

    secrets_region = os.getenv("AWS_REGION", "us-east-1")
    print(f"🌍 Using Secrets Manager region: {secrets_region}")
    secrets_client = boto3.client('secretsmanager', region_name=secrets_region)
    
    secret_response = secrets_client.get_secret_value(SecretId=secret_arn)
    secret_data = json.loads(secret_response['SecretString'])

    return {
        "HYDROLIX_HOST": secret_data.get('HYDROLIX_HOST'),
        "HYDROLIX_PORT": secret_data.get('HYDROLIX_PORT', '8088'),
        "HYDROLIX_USER": secret_data.get('HYDROLIX_USER'),
        "HYDROLIX_PASSWORD": secret_data.get('HYDROLIX_PASSWORD'),
    }


async def _process_hydrolix_stream(agent: Agent, query: str) -> str:
    """Process the agent stream and collect the response."""
    collected_text = []
    tool_active = False
    
    async for item in agent.stream_async(query):
        if "event" in item:
            event = item["event"]

            if "contentBlockStart" in event and "toolUse" in event[
                "contentBlockStart"
            ].get("start", {}):
                tool_active = True
                print(json.dumps({"event": event}))

            elif "contentBlockStop" in event and tool_active:
                tool_active = False
                print(json.dumps({"event": event}))

        elif "start_event_loop" in item:
            print(json.dumps(item))
        elif "current_tool_use" in item and tool_active:
            print(json.dumps(item["current_tool_use"]))
        elif "data" in item:
            collected_text.append(item["data"])
            print(item["data"], end="", flush=True)
    
    print()  # New line after streaming
    return "".join(collected_text)


@tool
def hydrolix_agent(query: str) -> str:
    """
    Analyze Hydrolix time-series data based on user questions.
    
    This subagent specializes in time-series data analysis using Hydrolix, including:
    - Streaming video analytics and CDN performance
    - CMCD (Common Media Client Data) metrics analysis
    - Buffer starvation and playback quality diagnostics
    - Regional and edge performance comparisons
    
    Args:
        query: User question about time-series data that needs to be analyzed
        
    Returns:
        str: Time-series data analysis results and insights
    """
    # Get context from singleton
    ctx = get_request_context()
    prompt_uuid = ctx.prompt_uuid or str(uuid4())
    user_timezone = ctx.user_timezone
    
    print(f"\n{'='*60}")
    print("📊 HYDROLIX TIME-SERIES ANALYST SUBAGENT")
    print(f"{'='*60}")
    print(f"📝 Query: {query}")
    print(f"🌍 Timezone: {user_timezone}")
    print(f"🆔 Prompt UUID: {prompt_uuid}")
    print(f"{'='*60}")
    
    try:
        # Get Hydrolix MCP environment configuration
        mcp_env = _get_hydrolix_mcp_env()
        
        print("\n🔌 INITIALIZING HYDROLIX MCP CLIENT")
        print("="*40)
        
        # Initialize MCP client for Hydrolix
        # Run mcp_hydrolix as a module (it's a package, not a standalone script)
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
            # Get tools from MCP server
            tools = hydrolix_mcp_server.list_tools_sync()
            tools.append(current_time)
            tools.append(calculator)
            
            # Initialize model
            model_id = os.getenv(
                "BEDROCK_MODEL_ID", 
                "us.anthropic.claude-sonnet-4-20250514-v1:0"
            )
            bedrock_model = BedrockModel(model_id=model_id)
            
            # Load system prompt
            system_prompt = _load_hydrolix_system_prompt(user_timezone)
            
            # Create agent with Hydrolix tools
            agent = Agent(
                model=bedrock_model,
                system_prompt=system_prompt,
                tools=tools,
                callback_handler=None,
            )
            
            print("🚀 Processing Hydrolix time-series analysis...")
            print(f"{'='*60}")
            
            # Stream the response using same pattern as orchestrator
            formatted_query = f"Analyze time-series data for this user question: {query}"
            text_response = asyncio.run(_process_hydrolix_stream(agent, formatted_query))
            
            print(f"\n{'='*60}")
            
            if text_response:
                return text_response
            
            return "I apologize, but I couldn't process your Hydrolix query request."

    except Exception as e:
        print(f"❌ Error in Hydrolix time-series analysis: {str(e)}")
        return f"Error processing Hydrolix query: {str(e)}"
