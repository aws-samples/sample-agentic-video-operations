# CMCD MCP Server

A Model Context Protocol (MCP) server for querying and analyzing Common Media Client Data (CMCD) metrics stored in InfluxDB.

## Overview

This server provides advanced tools to analyze streaming media performance data using the CMCD standard defined by the Consumer Technology Association (CTA). CMCD enables media players to communicate standardized playback telemetry to content delivery networks (CDNs) and origin servers.

## Features

### Available Tools

1. **get_average_bitrate**: Calculate average bitrate from CMCD metrics
   - Supports filtering by time range, session ID, and content ID
   - Returns average bitrate in kbps with detailed statistics

2. **get_session_details**: Retrieve detailed information about streaming sessions
   - Provides comprehensive session metrics including bitrate changes and buffer levels
   - Organizes data by CMCD field types

3. **analyze_buffer_events**: Analyze buffer-related events and rebuffering incidents
   - Identifies potential rebuffering events based on configurable thresholds
   - Provides detailed analysis of buffer level patterns

4. **identify_playback_errors**: Detect potential playback errors
   - Analyzes patterns for buffer underruns, sudden bitrate drops, and startup delays
   - Categorizes errors by severity level

### CMCD Metrics Supported

- **cmcd_bl**: Buffer level (milliseconds)
- **cmcd_br**: Bitrate (kbps)
- **cmcd_d**: Duration (milliseconds)
- **cmcd_mtp**: Media type
- **cmcd_su**: Startup delay (milliseconds)
- **cmcd_tb**: Target buffer (milliseconds)
- **time_taken**: Request processing time
- **edge_location**: CDN edge location

## Setup

### Prerequisites

- Python 3.8+
- InfluxDB instance with CMCD data
- Required Python packages (see requirements.txt)

### Environment Configuration

Create a `.env` file with the following variables:

```env
INFLUXDB_URL=https://your-influxdb-url:8086
INFLUXDB_TOKEN=your_influxdb_token
INFLUXDB_ORG=your_influxdb_org
VERIFY_SSL=False
```

### Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables in `.env` file

3. Run the server:
   ```bash
   python cmcd_server.py
   ```

## Data Schema

### Database Structure
- **Database**: `cmcd-metrics` 
- **Measurement**: `cloudfront_logs`
- **Time Series**: Data points with timestamps and CMCD field values

### Query Capabilities
- Time-based filtering with flexible ranges (-1h, -24h, -7d, etc.)
- Session-based analysis
- Content-specific metrics
- Edge location analysis
- Real-time and historical data processing

## Usage Examples

### MCP Configuration

Add to your MCP configuration file:

```json
{
  "mcpServers": {
    "cmcd-mcp": {
      "command": "python3",
      "args": ["/path/to/cmcd_server.py"],
      "cwd": "/path/to/mcp/directory"
    }
  }
}
```

### Tool Usage

1. **Average Bitrate Analysis**:
   - Get overall average bitrate for the last 24 hours
   - Filter by specific sessions or content
   - Analyze bitrate trends over time

2. **Session Analysis**:
   - Deep dive into individual streaming sessions
   - Track metric changes over session duration
   - Identify session-specific issues

3. **Buffer Event Analysis**:
   - Monitor rebuffering incidents
   - Set custom buffer level thresholds
   - Analyze buffer health patterns

4. **Error Detection**:
   - Automatic identification of playback issues
   - Severity-based error categorization
   - Root cause analysis support

## Logging

The server includes comprehensive logging:
- **Console Output**: Real-time debug information
- **Log File**: `cmcd_server.log` with rotation (10MB limit)
- **Debug Level**: Detailed query execution and result processing

## Error Handling

- Robust error handling for database connectivity issues
- Automatic bucket name detection and fallback
- Detailed error reporting with query information
- Graceful handling of missing or malformed data

## Performance Considerations

- Efficient Flux query generation
- Optimized data processing with minimal memory usage
- Connection pooling and proper resource cleanup
- Configurable query timeouts

## Troubleshooting

### Common Issues

1. **Connection Errors**: Verify InfluxDB URL and credentials
2. **No Data Found**: Check bucket names and measurement structure
3. **Query Timeouts**: Adjust time ranges or add more specific filters
4. **SSL Issues**: Set `VERIFY_SSL=False` for development environments

### Debug Mode

Enable detailed logging by checking the log file:
```bash
tail -f cmcd_server.log
```

## License

Licensed under the Apache License, Version 2.0

## Contributing

This server (`cmcd_server.py`) is designed for analyzing CMCD streaming media telemetry data. Contributions should focus on:
- Additional CMCD metric analysis tools
- Performance optimizations
- Enhanced error detection algorithms
- Better visualization support