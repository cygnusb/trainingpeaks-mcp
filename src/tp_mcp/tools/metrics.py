"""TOOL-08: tp_get_metrics / tp_get_metrics_insights - Health & sleep metrics."""

from datetime import date, timedelta
from typing import Any

from tp_mcp.client import TPClient


async def _get_athlete_id(client: TPClient) -> int | None:
    """Get athlete ID from profile."""
    if client.athlete_id:
        return client.athlete_id

    response = await client.get("/users/v3/user")
    if response.success and response.data:
        user_data = response.data.get("user", response.data)
        athlete_id = user_data.get("personId")
        if not athlete_id:
            athletes = user_data.get("athletes", [])
            if athletes:
                athlete_id = athletes[0].get("athleteId")
        client.athlete_id = athlete_id
        return athlete_id
    return None


def _parse_date_range(
    days: int,
    start_date: str | None,
    end_date: str | None,
) -> tuple[date, date, int] | dict:
    """Parse and validate date range. Returns (start, end, days) or error dict."""
    try:
        if start_date and end_date:
            q_start = date.fromisoformat(start_date)
            q_end = date.fromisoformat(end_date)
            if q_start > q_end:
                return {
                    "isError": True,
                    "error_code": "VALIDATION_ERROR",
                    "message": "start_date must be before end_date",
                }
            return q_start, q_end, (q_end - q_start).days
        else:
            if days < 1 or days > 365:
                return {
                    "isError": True,
                    "error_code": "VALIDATION_ERROR",
                    "message": "days must be between 1 and 365",
                }
            q_end = date.today()
            q_start = q_end - timedelta(days=days)
            return q_start, q_end, days
    except ValueError as e:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"Invalid date format. Use YYYY-MM-DD. Error: {e}",
        }


async def tp_get_metrics(
    days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Get daily health & sleep metrics (sleep hours, HRV, weight, etc.).

    Returns consolidated timed metrics per day with all available metric types
    such as Sleep Hours, Time in Deep/REM/Light Sleep, HRV, Body Weight, etc.

    Args:
        days: Days of history (default 30). Ignored if start_date/end_date provided.
        start_date: Optional start date (YYYY-MM-DD).
        end_date: Optional end date (YYYY-MM-DD).

    Returns:
        Dict with daily metric entries grouped by date.
    """
    parsed = _parse_date_range(days, start_date, end_date)
    if isinstance(parsed, dict):
        return parsed
    q_start, q_end, q_days = parsed

    async with TPClient() as client:
        athlete_id = await _get_athlete_id(client)
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/metrics/v3/athletes/{athlete_id}/consolidatedtimedmetrics/{q_start}/{q_end}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        if not response.data:
            return {
                "start_date": str(q_start),
                "end_date": str(q_end),
                "days": q_days,
                "data": [],
            }

        try:
            daily = []
            for entry in response.data:
                metrics = {}
                for detail in entry.get("details", []):
                    label = detail.get("label", f"type_{detail.get('type')}")
                    metrics[label] = detail.get("value")
                daily.append({
                    "date": entry.get("timeStamp", "").split("T")[0],
                    "metrics": metrics,
                    "source": entry.get("details", [{}])[0].get("uploadClient") if entry.get("details") else None,
                })

            return {
                "start_date": str(q_start),
                "end_date": str(q_end),
                "days": q_days,
                "data": daily,
            }
        except Exception as e:
            return {
                "isError": True,
                "error_code": "API_ERROR",
                "message": f"Failed to parse metrics data: {e}",
            }


async def tp_get_metrics_insights(
    days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Get health metric trends and insights (rolling mean, normal range).

    Returns time-series data per metric type with rolling mean and
    normal range (rangeHigh/rangeLow) once enough data is available.
    Useful for spotting trends in sleep, HRV, or other health metrics.

    Args:
        days: Days of history (default 30). Ignored if start_date/end_date provided.
        start_date: Optional start date (YYYY-MM-DD).
        end_date: Optional end date (YYYY-MM-DD).

    Returns:
        Dict with per-metric trend data including rolling mean and range.
    """
    parsed = _parse_date_range(days, start_date, end_date)
    if isinstance(parsed, dict):
        return parsed
    q_start, q_end, q_days = parsed

    async with TPClient() as client:
        athlete_id = await _get_athlete_id(client)
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/metrics/v4/athletes/{athlete_id}/metricsinsights/{q_start}/{q_end}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        if not response.data:
            return {
                "start_date": str(q_start),
                "end_date": str(q_end),
                "days": q_days,
                "metrics": [],
            }

        try:
            metrics = []
            for item in response.data:
                details = item.get("details", [])
                latest = details[-1] if details else {}
                metrics.append({
                    "label": item.get("label"),
                    "type": item.get("type"),
                    "source": item.get("uploadClient"),
                    "latest_value": latest.get("value"),
                    "rolling_mean": latest.get("mean"),
                    "range_low": latest.get("rangeLow"),
                    "range_high": latest.get("rangeHigh"),
                    "trend": details,
                })

            return {
                "start_date": str(q_start),
                "end_date": str(q_end),
                "days": q_days,
                "metrics": metrics,
            }
        except Exception as e:
            return {
                "isError": True,
                "error_code": "API_ERROR",
                "message": f"Failed to parse metrics insights: {e}",
            }
