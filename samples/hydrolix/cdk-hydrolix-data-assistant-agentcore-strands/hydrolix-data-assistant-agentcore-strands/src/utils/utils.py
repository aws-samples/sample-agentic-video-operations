"""
Store executed Hydrolix queries in the results table.

Items are keyed by the verified caller's `sub` (partition) and a millisecond timestamp
with a unique suffix (sort), so one user's records never mix with another's and two
records in the same millisecond don't overwrite each other. The runtime only writes; the
web app gets its records in the response stream, so no browser role reads this table.

QUESTION_ANSWERS_TABLE names the table (set by the CDK stack).
"""

import os
import threading
from uuid import uuid4

import boto3
from botocore.config import Config

from .query_record import QueryRecord

QUESTION_ANSWERS_TABLE = os.getenv("QUESTION_ANSWERS_TABLE")

# Short timeouts: the write runs inside the request, so during an AWS failure it must give up
# well before the request deadline instead of waiting out botocore's 60 s defaults.
QUICK = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
_dynamodb = None
_dynamodb_lock = threading.Lock()  # subagents write from their own threads


def _dynamodb_client():
    """The DynamoDB client, built on the first write and reused after."""
    global _dynamodb
    with _dynamodb_lock:
        if _dynamodb is None:
            region = os.getenv("AWS_REGION", "us-east-1")
            _dynamodb = boto3.client("dynamodb", region_name=region, config=QUICK)
        return _dynamodb


def save_query_record(actor_id: str, prompt_uuid: str, record: QueryRecord) -> bool:
    """Write one record; on failure log the class only (the item holds SQL) and go on."""
    if not QUESTION_ANSWERS_TABLE:
        print("⚠️ Query record not saved: QUESTION_ANSWERS_TABLE is not set")
        return False
    item = {
        "actor_id": {"S": actor_id},
        "recorded_at": {"S": f"{record.executed_at_ms:013d}#{uuid4().hex}"},
        "prompt_uuid": {"S": prompt_uuid},
        "agent_name": {"S": record.agent_name},
        "user_prompt": {"S": record.question},
        "sql_query": {"S": record.sql},
        "sql_query_description": {"S": record.purpose},
        "status": {"S": record.status},
        "truncated": {"BOOL": bool(record.omitted)},
        "omitted_characters": {"M": {name: {"N": str(n)} for name, n in record.omitted.items()}},
    }
    try:
        _dynamodb_client().put_item(TableName=QUESTION_ANSWERS_TABLE, Item=item)
    except Exception as error:
        print(f"❌ Query record not saved: {type(error).__name__}")
        return False
    return True
