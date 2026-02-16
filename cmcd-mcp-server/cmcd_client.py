import logging
import asyncio
import sys
from typing import Optional, List, Dict, Any
from contextlib import AsyncExitStack
import boto3
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool

MODEL_ID = "us.amazon.nova-pro-v1:0"

def setup_logger():
    logger = logging.getLogger('CMCDClient')
    logger.setLevel(logging.INFO)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger

logger = setup_logger()

class CMCDClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.bedrock = boto3.client('bedrock-runtime')
        self.model_id = MODEL_ID
        
    @staticmethod
    def convert_tool_to_json_spec(tool) -> dict:
        # Handle both Tool objects and dict representations
        if hasattr(tool, 'name'):
            name = tool.name
            description = tool.description
            input_schema = tool.inputSchema
        else:
            name = tool.get('name', '')
            description = tool.get('description', '')
            input_schema = tool.get('inputSchema', {})
        
        properties = {}
        for prop_name, prop_details in input_schema.get('properties', {}).items():
            prop_type = prop_details.get('type', 'string')
            description_prop = prop_details.get('description', '')
            
            properties[prop_name] = {
                "type": prop_type,
                "description": description_prop
            }

        return {
            "name": name,
            "description": description,
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": properties,
                    "required": input_schema.get('required', [])
                }
            }
        }

    @staticmethod
    def convert_content_to_json(content_obj: Any, tool_use_id: str = "default_tool_id") -> Dict[str, Any]:
        # Extract text content from MCP response
        if isinstance(content_obj, list):
            text_content = "\n".join([item.text if hasattr(item, 'text') else str(item) for item in content_obj])
        elif hasattr(content_obj, 'text'):
            text_content = content_obj.text
        else:
            text_content = str(content_obj)

        status = "error" if getattr(content_obj, 'isError', False) else "success"
        
        return {
            "role": "user",
            "content": [{
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"text": text_content}],
                    "status": status
                }
            }]
        }

    async def process_query(self, query: str, session: ClientSession) -> str:
        logger.info("Processing query: %s", query)
        
        tools_response = await session.list_tools()
        tools = tools_response.tools if hasattr(tools_response, 'tools') else tools_response
        
        list_of_tools = []
        for tool in tools:
            tools_json = self.convert_tool_to_json_spec(tool)
            list_of_tools.append({"toolSpec": tools_json})

        available_tools = {"tools": list_of_tools}

        messages = [{
            "role": "user",
            "content": [{"text": query}]
        }]

        # Get server prompts for better context
        server_prompt = "You are a CMCD streaming analytics assistant. Use the available tools to analyze streaming media performance data."
        try:
            prompts_response = await session.list_prompts()
            prompts = prompts_response.prompts if hasattr(prompts_response, 'prompts') else prompts_response
            if prompts:
                # Use the first available prompt from server
                prompt_result = await session.get_prompt(prompts[0].name, {})
                if hasattr(prompt_result, 'messages') and prompt_result.messages:
                    server_prompt = prompt_result.messages[0].content.text
        except Exception as e:
            logger.debug(f"Using default prompt: {e}")
        
        system_prompts = [{"text": server_prompt}]
        final_text = []

        while True:
            response = self.bedrock.converse(
                modelId=self.model_id,
                messages=messages,
                system=system_prompts,
                toolConfig=available_tools,
            )

            output_message = response['output']['message']
            messages.append(output_message)

            for content in output_message['content']:
                if 'text' in content:
                    final_text.append(content['text'])
                elif 'toolUse' in content:
                    tool_name = content['toolUse']['name']
                    tool_args = content['toolUse']['input']
                    
                    logger.info("Executing tool: %s", tool_name)
                    result = await session.call_tool(tool_name, tool_args)
                    
                    toolResult = self.convert_content_to_json(result.content, content['toolUse']['toolUseId'])
                    messages.append(toolResult)
            
            if not any('toolUse' in content for content in output_message['content']):
                break

        return "\n".join(final_text)

    async def chat_loop(self, session: ClientSession):
        logger.info("CMCD Client Started!")
        
        # List available tools
        tools_response = await session.list_tools()
        tools = tools_response.tools if hasattr(tools_response, 'tools') else tools_response
        
        print("\nAvailable tools:")
        for i, tool in enumerate(tools, 1):
            name = tool.name if hasattr(tool, 'name') else tool.get('name', 'Unknown')
            desc = tool.description if hasattr(tool, 'description') else tool.get('description', 'No description')
            print(f"{i}. {name}: {desc}")
        
        # List available prompts
        try:
            prompts_response = await session.list_prompts()
            prompts = prompts_response.prompts if hasattr(prompts_response, 'prompts') else prompts_response
            if prompts:
                print("\nAvailable prompts:")
                for i, prompt in enumerate(prompts, 1):
                    name = prompt.name if hasattr(prompt, 'name') else prompt.get('name', 'Unknown')
                    desc = prompt.description if hasattr(prompt, 'description') else prompt.get('description', 'No description')
                    print(f"{i}. {name}: {desc}")
        except Exception as e:
            logger.debug(f"No prompts available: {e}")
        
        # List available resources
        try:
            resources_response = await session.list_resources()
            resources = resources_response.resources if hasattr(resources_response, 'resources') else resources_response
            if resources:
                print("\nAvailable resources:")
                for i, resource in enumerate(resources, 1):
                    uri = resource.uri if hasattr(resource, 'uri') else resource.get('uri', 'Unknown')
                    name = resource.name if hasattr(resource, 'name') else resource.get('name', uri)
                    print(f"{i}. {name} ({uri})")
        except Exception as e:
            logger.debug(f"No resources available: {e}")
        
        logger.info("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == 'quit':
                    break

                response = await self.process_query(query, session)
                print("\n" + response)

            except Exception as e:
                logger.error("Error: %s", str(e))

async def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python cmcd_client.py <path_to_cmcd_server.py>")
        sys.exit(1)

    server_script_path = sys.argv[1]
    cmcd_client = CMCDClient()
    
    server_params = StdioServerParameters(
        command="python", args=[server_script_path]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await cmcd_client.chat_loop(session)

if __name__ == "__main__":
    asyncio.run(main())