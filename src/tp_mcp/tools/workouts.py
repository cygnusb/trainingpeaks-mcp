"""TOOL-03 to TOOL-07: Workout read and CRUD tools."""

from datetime import date as date_cls
from typing import Any, Literal

from tp_mcp.client import TPClient, WorkoutCreateRequest, WorkoutUpdateRequest, parse_workout_detail, parse_workout_list

VALID_SPORTS = {"Bike", "Run", "Swim", "Strength", "MTB", "XCSkiing", "Rowing", "Triathlon", "Other"}


async def _get_athlete_id(client: TPClient) -> int | None:
    """Get athlete ID from profile."""
    if client.athlete_id:
        return client.athlete_id

    response = await client.get("/users/v3/user")
    if response.success and response.data:
        # API returns nested structure: { user: { ... } }
        user_data = response.data.get("user", response.data)

        # Try personId first, then athletes array
        athlete_id = user_data.get("personId")
        if not athlete_id:
            athletes = user_data.get("athletes", [])
            if athletes:
                athlete_id = athletes[0].get("athleteId")

        client.athlete_id = athlete_id
        return athlete_id
    return None


async def tp_get_workouts(
    start_date: str,
    end_date: str,
    workout_filter: Literal["all", "planned", "completed"] = "all",
) -> dict[str, Any]:
    """Get workouts for a date range.

    Args:
        start_date: Start date in ISO format (YYYY-MM-DD).
        end_date: End date in ISO format (YYYY-MM-DD).
        workout_filter: Filter by status - "all", "planned", or "completed".

    Returns:
        Dict with workouts list, count, and date_range.
    """
    # Validate dates
    try:
        start = date_cls.fromisoformat(start_date)
        end = date_cls.fromisoformat(end_date)
    except ValueError as e:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"Invalid date format: {e}. Use YYYY-MM-DD.",
        }

    if start > end:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "start_date must be before or equal to end_date",
        }

    # Limit date range to prevent massive queries
    max_days = 90
    if (end - start).days > max_days:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"Date range too large. Max {max_days} days. Use smaller queries.",
        }

    async with TPClient() as client:
        athlete_id = await _get_athlete_id(client)
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        # Format dates for API
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{start_str}/{end_str}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        if not response.data:
            return {
                "workouts": [],
                "count": 0,
                "date_range": {"start": start_date, "end": end_date},
            }

        try:
            workouts = parse_workout_list(response.data)

            # Apply filter
            if workout_filter == "planned":
                workouts = [w for w in workouts if not w.is_completed]
            elif workout_filter == "completed":
                workouts = [w for w in workouts if w.is_completed]

            # Convert to dict format for response
            workout_dicts = [
                {
                    "id": str(w.id),
                    "date": w.date.isoformat(),
                    "title": w.title,
                    "type": w.workout_status,
                    "sport": w.sport,
                    "duration_planned": w.duration_planned,
                    "duration_actual": w.duration_actual,
                    "tss": w.tss_actual or w.tss_planned,
                    "description": w.description,
                }
                for w in workouts
            ]

            return {
                "workouts": workout_dicts,
                "count": len(workout_dicts),
                "date_range": {"start": start_date, "end": end_date},
            }

        except Exception as e:
            return {
                "isError": True,
                "error_code": "API_ERROR",
                "message": f"Failed to parse workouts: {e}",
            }


async def tp_get_workout(workout_id: str) -> dict[str, Any]:
    """Get full details for a single workout.

    Args:
        workout_id: The workout ID.

    Returns:
        Dict with full workout details including structure.
    """
    async with TPClient() as client:
        athlete_id = await _get_athlete_id(client)
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        if not response.data:
            return {
                "isError": True,
                "error_code": "NOT_FOUND",
                "message": f"Workout {workout_id} not found",
            }

        try:
            workout = parse_workout_detail(response.data)

            return {
                "id": str(workout.id),
                "date": workout.date.isoformat(),
                "title": workout.title,
                "sport": workout.sport,
                "workout_type": workout.workout_type,
                "description": workout.description,
                "coach_comments": workout.coach_comments,
                "athlete_comments": workout.athlete_comments,
                "metrics": {
                    "duration_planned": workout.duration_planned,
                    "duration_actual": workout.duration_actual,
                    "tss_planned": workout.tss_planned,
                    "tss_actual": workout.tss_actual,
                    "if_planned": workout.if_planned,
                    "if_actual": workout.if_actual,
                    "distance_planned": workout.distance_planned,
                    "distance_actual": workout.distance_actual,
                    "avg_power": workout.avg_power,
                    "normalized_power": workout.normalized_power,
                    "avg_hr": workout.avg_hr,
                    "avg_cadence": workout.avg_cadence,
                    "elevation_gain": workout.elevation_gain,
                    "calories": workout.calories,
                },
                "completed": workout.completed,
            }

        except Exception as e:
            return {
                "isError": True,
                "error_code": "API_ERROR",
                "message": f"Failed to parse workout: {e}",
            }


async def tp_create_workout(
    date: str,
    sport: str,
    title: str,
    description: str | None = None,
    coach_comments: str | None = None,
    duration_planned: int | float | None = None,
    distance_planned: float | None = None,
    tss_planned: float | None = None,
    if_planned: float | None = None,
    workout_type: str | int | None = None,
) -> dict[str, Any]:
    """Create a new planned workout.

    Args:
        date: Workout date in ISO format (YYYY-MM-DD).
        sport: Sport type (Bike, Run, Swim, Strength, MTB, XCSkiing, Rowing, Triathlon, Other).
        title: Workout title.
        description: Optional workout description.
        coach_comments: Optional coach notes.
        duration_planned: Planned duration in seconds.
        distance_planned: Planned distance in meters.
        tss_planned: Planned Training Stress Score (>= 0).
        if_planned: Planned Intensity Factor (0.0 - 1.5).
        workout_type: Optional workout type value ID.

    Returns:
        Dict with created workout details.
    """
    # Validate date
    try:
        date_cls.fromisoformat(date)
    except ValueError as e:
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": f"Invalid date: {e}. Use YYYY-MM-DD."}

    # Validate sport
    if sport not in VALID_SPORTS:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"Invalid sport '{sport}'. Valid: {', '.join(sorted(VALID_SPORTS))}",
        }

    # Validate title
    if not title or not title.strip():
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "title must not be empty."}

    # Validate IF
    if if_planned is not None and not (0.0 <= if_planned <= 1.5):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "if_planned must be between 0.0 and 1.5."}

    # Validate TSS
    if tss_planned is not None and tss_planned < 0:
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "tss_planned must be >= 0."}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        request = WorkoutCreateRequest(
            workoutDay=date,
            workoutTypeFamilyId=sport,
            title=title,
            description=description,
            coachComments=coach_comments,
            totalTimePlanned=duration_planned,
            distancePlanned=distance_planned,
            tssPlanned=tss_planned,
            ifPlanned=if_planned,
            workoutTypeValueId=workout_type,
        )
        payload = request.to_api_payload()

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts"
        response = await client.post(endpoint, json=payload)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        data = response.data or {}
        return {
            "id": str(data.get("workoutId", "")),
            "date": data.get("workoutDay", date),
            "title": data.get("title", title),
            "sport": data.get("workoutTypeFamilyId", sport),
            "metrics": {
                "duration_planned": data.get("totalTimePlanned"),
                "distance_planned": data.get("distancePlanned"),
                "tss_planned": data.get("tssPlanned"),
                "if_planned": data.get("ifPlanned"),
            },
            "message": "Workout created successfully.",
        }


async def tp_update_workout(
    workout_id: str,
    date: str | None = None,
    sport: str | None = None,
    title: str | None = None,
    description: str | None = None,
    coach_comments: str | None = None,
    duration_planned: int | float | None = None,
    distance_planned: float | None = None,
    tss_planned: float | None = None,
    if_planned: float | None = None,
    workout_type: str | int | None = None,
) -> dict[str, Any]:
    """Update an existing planned workout.

    Args:
        workout_id: The workout ID to update.
        date: New date in ISO format (YYYY-MM-DD).
        sport: New sport type.
        title: New title.
        description: New description.
        coach_comments: New coach notes.
        duration_planned: New planned duration in seconds.
        distance_planned: New planned distance in meters.
        tss_planned: New planned TSS (>= 0).
        if_planned: New planned IF (0.0 - 1.5).
        workout_type: New workout type value ID.

    Returns:
        Dict with updated workout details.
    """
    # Validate workout_id
    if not workout_id or not str(workout_id).strip().lstrip("-").isdigit():
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "workout_id must be a numeric ID."}

    # Require at least one field
    update_fields = [date, sport, title, description, coach_comments, duration_planned, distance_planned, tss_planned, if_planned, workout_type]
    if all(f is None for f in update_fields):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "At least one field must be provided to update."}

    # Validate date if provided
    if date is not None:
        try:
            date_cls.fromisoformat(date)
        except ValueError as e:
            return {"isError": True, "error_code": "VALIDATION_ERROR", "message": f"Invalid date: {e}. Use YYYY-MM-DD."}

    # Validate sport if provided
    if sport is not None and sport not in VALID_SPORTS:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"Invalid sport '{sport}'. Valid: {', '.join(sorted(VALID_SPORTS))}",
        }

    # Validate IF
    if if_planned is not None and not (0.0 <= if_planned <= 1.5):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "if_planned must be between 0.0 and 1.5."}

    # Validate TSS
    if tss_planned is not None and tss_planned < 0:
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "tss_planned must be >= 0."}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        request = WorkoutUpdateRequest(
            workoutDay=date,
            workoutTypeFamilyId=sport,
            title=title,
            description=description,
            coachComments=coach_comments,
            totalTimePlanned=duration_planned,
            distancePlanned=distance_planned,
            tssPlanned=tss_planned,
            ifPlanned=if_planned,
            workoutTypeValueId=workout_type,
        )
        payload = request.to_api_payload()

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}"
        response = await client.put(endpoint, json=payload)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        data = response.data or {}
        return {
            "id": str(data.get("workoutId", workout_id)),
            "date": data.get("workoutDay"),
            "title": data.get("title"),
            "sport": data.get("workoutTypeFamilyId"),
            "metrics": {
                "duration_planned": data.get("totalTimePlanned"),
                "distance_planned": data.get("distancePlanned"),
                "tss_planned": data.get("tssPlanned"),
                "if_planned": data.get("ifPlanned"),
            },
            "message": "Workout updated successfully.",
        }


async def tp_delete_workout(workout_id: str) -> dict[str, Any]:
    """Delete a planned workout. This action is irreversible.

    Args:
        workout_id: The workout ID to delete.

    Returns:
        Dict with confirmation message.
    """
    if not workout_id or not str(workout_id).strip().lstrip("-").isdigit():
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "workout_id must be a numeric ID."}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}"
        response = await client.delete(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        return {"message": f"Workout {workout_id} deleted successfully."}
