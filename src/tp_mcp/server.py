"""MCP Server implementation for TrainingPeaks."""

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

from tp_mcp.auth import get_credential, validate_auth
from tp_mcp.tools import (
    tp_analyze_workout,
    tp_auth_status,
    tp_create_workout,
    tp_delete_workout,
    tp_get_fitness,
    tp_get_peaks,
    tp_get_profile,
    tp_get_workout,
    tp_get_workout_prs,
    tp_get_workouts,
    tp_refresh_auth,
    tp_update_workout,
)

# Configure logging to stderr (stdout is used for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("tp-mcp")

# Create the MCP server
server = Server("trainingpeaks-mcp")


# Tool descriptions: concise but guide LLM to efficient usage
TOOLS = [
    Tool(
        name="tp_auth_status",
        description="Check auth status. Use only when other tools return auth errors.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="tp_get_profile",
        description="Get athlete profile. Rarely needed - other tools work without it.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="tp_get_workouts",
        description="List workouts in date range. Query only days needed. Max 90 days.",
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "YYYY-MM-DD. Be precise - query only days you need.",
                },
                "end_date": {
                    "type": "string",
                    "description": "YYYY-MM-DD. Be precise - query only days you need.",
                },
                "type": {
                    "type": "string",
                    "enum": ["all", "planned", "completed"],
                    "description": "Filter: all, planned, or completed",
                    "default": "all",
                },
            },
            "required": ["start_date", "end_date"],
        },
    ),
    Tool(
        name="tp_get_workout",
        description="Get workout details by ID. Use after tp_get_workouts.",
        inputSchema={
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "Workout ID from tp_get_workouts",
                },
            },
            "required": ["workout_id"],
        },
    ),
    Tool(
        name="tp_get_workout_prs",
        description="Get PRs set during a specific workout.",
        inputSchema={
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "Workout ID from tp_get_workouts",
                },
            },
            "required": ["workout_id"],
        },
    ),
    Tool(
        name="tp_get_peaks",
        description="Get top performances by type. For comparing PRs over time.",
        inputSchema={
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "enum": ["Bike", "Run"],
                    "description": "Bike or Run",
                },
                "pr_type": {
                    "type": "string",
                    "description": "Bike: power1min/5min/20min. Run: speed5K/10K/Half",
                },
                "days": {
                    "type": "integer",
                    "description": "Lookback days. Default 3650 (all-time).",
                    "default": 3650,
                },
            },
            "required": ["sport", "pr_type"],
        },
    ),
    Tool(
        name="tp_get_fitness",
        description="Get fitness/fatigue trend (CTL/ATL/TSB). Supports historical date ranges.",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days from today (default 90). Ignored if dates provided.",
                    "default": 90,
                },
                "start_date": {
                    "type": "string",
                    "description": "YYYY-MM-DD. For historical queries (e.g., 2022-01-01).",
                },
                "end_date": {
                    "type": "string",
                    "description": "YYYY-MM-DD. For historical queries (e.g., 2022-03-01).",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="tp_analyze_workout",
        description=(
            "Get workout analysis: metrics, zones, laps."
            " Saves full time-series to JSON file. Use after tp_get_workouts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "Workout ID from tp_get_workouts",
                },
            },
            "required": ["workout_id"],
        },
    ),
    Tool(
        name="tp_refresh_auth",
        description="Refresh auth by extracting cookie from user's browser. Use when other tools return auth errors.",
        inputSchema={
            "type": "object",
            "properties": {
                "browser": {
                    "type": "string",
                    "enum": ["auto", "chrome", "firefox", "safari", "edge"],
                    "description": "Browser to extract from. Use 'auto' to try all.",
                    "default": "auto",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="tp_create_workout",
        description="Create a new planned workout. Returns the created workout with its ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Workout date in YYYY-MM-DD format.",
                },
                "sport": {
                    "type": "string",
                    "enum": ["Bike", "Run", "Swim", "Strength", "MTB", "XCSkiing", "Rowing", "Triathlon", "Other"],
                    "description": "Sport type.",
                },
                "title": {
                    "type": "string",
                    "description": "Workout title.",
                },
                "description": {
                    "type": "string",
                    "description": "Workout description.",
                },
                "coach_comments": {
                    "type": "string",
                    "description": "Coach notes.",
                },
                "duration_planned": {
                    "type": "number",
                    "description": "Planned duration in seconds.",
                },
                "distance_planned": {
                    "type": "number",
                    "description": "Planned distance in meters.",
                },
                "tss_planned": {
                    "type": "number",
                    "description": "Planned Training Stress Score (>= 0).",
                },
                "if_planned": {
                    "type": "number",
                    "description": "Planned Intensity Factor (0.0 - 1.5).",
                },
                "workout_type": {
                    "description": "Optional workout type value ID.",
                },
            },
            "required": ["date", "sport", "title"],
        },
    ),
    Tool(
        name="tp_update_workout",
        description="Update an existing planned workout. Provide only the fields to change.",
        inputSchema={
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "Workout ID to update.",
                },
                "date": {
                    "type": "string",
                    "description": "New date in YYYY-MM-DD format.",
                },
                "sport": {
                    "type": "string",
                    "enum": ["Bike", "Run", "Swim", "Strength", "MTB", "XCSkiing", "Rowing", "Triathlon", "Other"],
                    "description": "New sport type.",
                },
                "title": {
                    "type": "string",
                    "description": "New title.",
                },
                "description": {
                    "type": "string",
                    "description": "New description.",
                },
                "coach_comments": {
                    "type": "string",
                    "description": "New coach notes.",
                },
                "duration_planned": {
                    "type": "number",
                    "description": "New planned duration in seconds.",
                },
                "distance_planned": {
                    "type": "number",
                    "description": "New planned distance in meters.",
                },
                "tss_planned": {
                    "type": "number",
                    "description": "New planned TSS (>= 0).",
                },
                "if_planned": {
                    "type": "number",
                    "description": "New planned IF (0.0 - 1.5).",
                },
                "workout_type": {
                    "description": "New workout type value ID.",
                },
            },
            "required": ["workout_id"],
        },
    ),
    Tool(
        name="tp_delete_workout",
        description="Delete a planned workout permanently. This action is irreversible.",
        inputSchema={
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "Workout ID to delete.",
                },
            },
            "required": ["workout_id"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    logger.info(f"Tool call: {name}")

    try:
        result: dict[str, Any]

        if name == "tp_auth_status":
            result = await tp_auth_status()

        elif name == "tp_get_profile":
            result = await tp_get_profile()

        elif name == "tp_get_workouts":
            result = await tp_get_workouts(
                start_date=arguments["start_date"],
                end_date=arguments["end_date"],
                workout_filter=arguments.get("type", "all"),
            )

        elif name == "tp_get_workout":
            result = await tp_get_workout(
                workout_id=arguments["workout_id"],
            )

        elif name == "tp_get_workout_prs":
            result = await tp_get_workout_prs(
                workout_id=arguments["workout_id"],
            )

        elif name == "tp_get_peaks":
            result = await tp_get_peaks(
                sport=arguments["sport"],
                pr_type=arguments["pr_type"],
                days=arguments.get("days", 3650),
            )

        elif name == "tp_get_fitness":
            result = await tp_get_fitness(
                days=arguments.get("days", 90),
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
            )

        elif name == "tp_analyze_workout":
            result = await tp_analyze_workout(
                workout_id=arguments["workout_id"],
            )

        elif name == "tp_refresh_auth":
            result = await tp_refresh_auth(
                browser=arguments.get("browser", "auto"),
            )

        elif name == "tp_create_workout":
            result = await tp_create_workout(
                date=arguments["date"],
                sport=arguments["sport"],
                title=arguments["title"],
                description=arguments.get("description"),
                coach_comments=arguments.get("coach_comments"),
                duration_planned=arguments.get("duration_planned"),
                distance_planned=arguments.get("distance_planned"),
                tss_planned=arguments.get("tss_planned"),
                if_planned=arguments.get("if_planned"),
                workout_type=arguments.get("workout_type"),
            )

        elif name == "tp_update_workout":
            result = await tp_update_workout(
                workout_id=arguments["workout_id"],
                date=arguments.get("date"),
                sport=arguments.get("sport"),
                title=arguments.get("title"),
                description=arguments.get("description"),
                coach_comments=arguments.get("coach_comments"),
                duration_planned=arguments.get("duration_planned"),
                distance_planned=arguments.get("distance_planned"),
                tss_planned=arguments.get("tss_planned"),
                if_planned=arguments.get("if_planned"),
                workout_type=arguments.get("workout_type"),
            )

        elif name == "tp_delete_workout":
            result = await tp_delete_workout(
                workout_id=arguments["workout_id"],
            )

        else:
            result = {
                "isError": True,
                "error_code": "UNKNOWN_TOOL",
                "message": f"Unknown tool: {name}",
            }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.exception(f"Error in tool {name}")
        error_result = {
            "isError": True,
            "error_code": "API_ERROR",
            "message": str(e),
        }
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]


async def _validate_auth_on_startup() -> bool:
    """Validate authentication on server startup.

    Returns:
        True if auth is valid, False otherwise.
    """
    cred = get_credential()
    if not cred.success or not cred.cookie:
        logger.warning("No credential stored. Run 'tp-mcp auth' to authenticate.")
        return False

    result = await validate_auth(cred.cookie)
    if result.is_valid:
        logger.info(f"Authenticated as {result.email} (athlete_id: {result.athlete_id})")
        return True
    else:
        logger.warning(f"Authentication invalid: {result.message}")
        return False


async def run_server_async() -> None:
    """Run the MCP server (async)."""
    logger.info("Starting TrainingPeaks MCP Server")

    # Validate auth on startup (warning only, don't block)
    await _validate_auth_on_startup()

    # Run the server with stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run_server() -> int:
    """Run the MCP server (entry point).

    Returns:
        Exit code.
    """
    try:
        asyncio.run(run_server_async())
        return 0
    except KeyboardInterrupt:
        logger.info("Server stopped")
        return 0
    except Exception as e:
        logger.exception(f"Server error: {e}")
        return 1
