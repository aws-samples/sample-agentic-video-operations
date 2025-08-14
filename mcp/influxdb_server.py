# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""awslabs Timestream for InfluxDB MCP Server implementation."""

import boto3
import os
from influxdb_client.client.influxdb_client import InfluxDBClient
from influxdb_client.client.write.point import Point
from influxdb_client.client.write_api import ASYNCHRONOUS, SYNCHRONOUS
from influxdb_client.domain.write_precision import WritePrecision
import sys
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("influxdb_server.log", rotation="10 MB", level="INFO")
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# Get the environment variables
INFLUXDB_URL = os.getenv('INFLUXDB_URL')
INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN')
INFLUXDB_ORG = os.getenv('INFLUXDB_ORG')
VERIFY_SSL = os.getenv('VERIFY_SSL', 'False').lower() == 'true'


# Define Field parameters as global variables to avoid duplication
REQUIRED_FIELD_QUERY = Field(..., description='The Flux query string.')

mcp = FastMCP(
    'cmcd-influxdb-mcp-server',
    instructions="""
    Direct InfluxDB query interface for Common Media Client Data (CMCD) analytics.
    
    This server provides raw Flux query execution against CMCD streaming telemetry data stored in InfluxDB.
    Use this when you need custom queries beyond the pre-built analytics tools in the main CMCD server.
    
    Data Schema:
    - Bucket: cmcd-metrics
    - Measurement: cloudfront_logs
    - Fields: cmcd_bl (buffer length), cmcd_br (bitrate), cmcd_bs (buffer starved), 
             cmcd_d (duration), cmcd_mtp (throughput), cmcd_su (startup), cmcd_tb (top bitrate)
    - Tags: cmcd_sid (session ID), cmcd_cid (content ID), edge_location
    
    Requires Flux query language knowledge. For common analytics, use the main CMCD MCP server instead.
    """,
    dependencies=['loguru', 'boto3', 'influxdb-client'],
)


def get_timestream_influxdb_client():
    """Get the AWS Timestream for InfluxDB client."""
    aws_region: str = os.environ.get('AWS_REGION', 'us-east-1')
    aws_profile = os.environ.get('AWS_PROFILE')
    try:
        if aws_profile:
            logger.info(f'Using AWS profile for AWS Timestream Influx Client: {aws_profile}')
            client = boto3.Session(profile_name=aws_profile, region_name=aws_region).client(
                'timestream-influxdb'
            )
        else:
            client = boto3.Session(region_name=aws_region).client('timestream-influxdb')
    except Exception as e:
        logger.error(f'Error creating AWS Timestream for InfluxDB client: {str(e)}')
        raise

    return client


def get_influxdb_client(url, token, org=None, timeout=10000, verify_ssl: bool = False):
    """Get an InfluxDB client.

    Args:
        url: The URL of the InfluxDB server e.g. https://<host-name>:8086.
        token: The authentication token.
        org: The organization name.
        timeout: The timeout in milliseconds.
        verify_ssl: whether to verify SSL with https connections

    Returns:
        An InfluxDB client.

    Raises:
        ValueError: If the URL does not use HTTPS protocol or is not properly formatted.
    """
    try:
        parsed_url = urlparse(url)
        url_scheme = parsed_url.scheme
        if url_scheme != 'https' and url_scheme != 'http':
            raise ValueError('URL must use HTTP(S) protocol')
    except Exception as e:
        logger.error(f'Error parsing URL: {str(e)}')
        raise

    if not token:
        raise ValueError('Token must be provided')

    # Ensure org is not None when passed to InfluxDBClient
    org_param = org if org is not None else ''

    return InfluxDBClient(
        url=url, token=token, org=org_param, timeout=timeout, verify_ssl=verify_ssl
    )


@mcp.tool(name='cmcd_query', description='Query CMCD data from InfluxDB using Flux query language.')
async def influxdb_query(
    query: str = REQUIRED_FIELD_QUERY,
    url: str = INFLUXDB_URL,
    token: str = INFLUXDB_TOKEN,
    org: str = INFLUXDB_ORG,
    verify_ssl: bool = VERIFY_SSL,
) -> Dict[str, Any]:
    """Use this tool to query the cmcd database directly for data. This tool should only be used if specialized tools available in the CMCD MCP server

    The database contains the following fields 
    cmcd_bl is The buffer length associated with the media object being requested.
    cmcd_br The encoded bitrate of the audio or video object 
    cmcd_bs Key is included without a value if the buffer was starved at some point between the prior request and this object request, resulting in the player being in a rebuffering state and the video or audio playback being stalled
    cmcd_d The playback duration in milliseconds of the object being requested, this is the duration of the segment not the entire video. if the query is about how long an asset has been viewed, all the cmcd_d values for a particular session id need to be added up 
    cmcd_mtp The throughput between client and server, as measured by the client
    cmcd_su Key is included without a value if the object is needed urgently due to startup, seeking or recovery after a buffer-empty event.
    cmcd_tb The highest bitrate rendition in the manifest or playlist that the client is allowed to play,

    the input needs to be in Flux query 

    Returns:
        Query results in the specified format.
    """
    try:
        client = get_influxdb_client(url, token, org, verify_ssl)
        query_api = client.query_api()
        logger.info("executing query")
        logger.info(query)

        # Return as JSON
        tables = query_api.query(org=org, query=query)

        # Process the tables into a more usable format
        result = []
        for table in tables:
            for record in table.records:
                try:
                    result.append(
                        {
                            'measurement': record.get_measurement() if hasattr(record, 'get_measurement') else None,
                            'field': record.get_field() if hasattr(record, 'get_field') else None,
                            'value': record.get_value() if hasattr(record, 'get_value') else record.values.get('_value'),
                            'time': record.get_time().isoformat() if record.get_time() else None,
                            'tags': record.values.get('tags', {}),
                            'raw_values': dict(record.values)
                        }
                    )
                except Exception as e:
                    logger.debug(f"Error processing record: {e}")
                    # Fallback: include raw values
                    result.append({
                        'raw_values': dict(record.values),
                        'value': record.values.get('_value'),
                        'time': None
                    })
                logger.debug(f"Processed record: {record.values}")

        client.close()

        logger.info(f'Query returned {len(result)} records')
        

        return {'status': 'success', 'result': result, 'format': 'json'}

    except Exception as e:
        logger.error(f'Error querying InfluxDB: {str(e)}')
        return {'status': 'error', 'message': str(e)}


def main():
    """Main entry point for the MCP server application."""
    logger.info('Starting Timestream for InfluxDB MCP Server')
    mcp.run()


if __name__ == '__main__':
    main()