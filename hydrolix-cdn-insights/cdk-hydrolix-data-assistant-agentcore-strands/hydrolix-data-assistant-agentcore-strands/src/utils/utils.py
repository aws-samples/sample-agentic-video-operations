"""
Utility Functions for Hydrolix Data Analyst Assistant

This module provides utility functions for storing and retrieving Hydrolix
analysis data from DynamoDB. It handles the formatting and processing of SQL query
results and analysis data for storage and retrieval.

The module uses the following environment variables:
- QUESTION_ANSWERS_TABLE: DynamoDB table for storing query results and analysis data
"""

import boto3
import json
import os
from datetime import datetime

# Load configuration from environment variables
QUESTION_ANSWERS_TABLE = os.getenv('QUESTION_ANSWERS_TABLE')


def save_raw_query_result(
    user_prompt_uuid, 
    user_prompt, 
    sql_query, 
    sql_query_description, 
    result, 
    message,
    agent_name=None
):
    """
    Save Hydrolix analysis query results to DynamoDB for audit trail and future reference.

    This function stores comprehensive information about each SQL query execution including
    the original user question, the generated SQL query, results, and metadata for
    tracking and auditing purposes.

    Args:
        user_prompt_uuid (str): Unique identifier for the user prompt/analysis session
        user_prompt (str): The original user question about Hydrolix data
        sql_query (str): The executed SQL query against the Hydrolix database
        sql_query_description (str): Human-readable description of what the query analyzes
        result (dict): The query results and metadata
        message (str): Additional information about the result (e.g., truncation notices)
        agent_name (str, optional): Name of the agent that executed the query

    Returns:
        dict: Response with success status and DynamoDB response or error details
    """
    try:
        # Check if the table name is available
        if not QUESTION_ANSWERS_TABLE:
            return {"success": False, "error": "QUESTION_ANSWERS_TABLE environment variable not set"}

        dynamodb_client = boto3.client("dynamodb")

        item = {
            "id": {"S": user_prompt_uuid},
            "my_timestamp": {"N": str(int(datetime.now().timestamp()))},
            "datetime": {"S": str(datetime.now())},
            "user_prompt": {"S": user_prompt},
            "sql_query": {"S": sql_query},
            "sql_query_description": {"S": sql_query_description},
            "data": {"S": json.dumps(result)},
            "message_result": {"S": message},
        }
        
        # Add agent_name if provided
        if agent_name:
            item["agent_name"] = {"S": agent_name}

        response = dynamodb_client.put_item(
            TableName=QUESTION_ANSWERS_TABLE,
            Item=item,
        )

        print("\n" + "=" * 70)
        print("✅ HYDROLIX ANALYSIS DATA SAVED TO DYNAMODB")
        print("=" * 70)
        print(f"🆔 Session ID: {user_prompt_uuid}")
        print(f"📊 DynamoDB Table: {QUESTION_ANSWERS_TABLE}")
        if agent_name:
            print(f"🤖 Agent: {agent_name}")
        print("=" * 70 + "\n")
        return {"success": True, "response": response}

    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ HYDROLIX ANALYSIS DATA SAVE ERROR")
        print("=" * 70)
        print(f"📊 DynamoDB Table: {QUESTION_ANSWERS_TABLE}")
        print(f"❌ Error: {str(e)}")
        print("=" * 70 + "\n")
        return {"success": False, "error": str(e)}
