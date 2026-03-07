"""TOOL-03 to TOOL-07: Workout read and CRUD tools."""

import base64
from datetime import date as date_cls
import gzip
import json
from pathlib import Path
import tempfile
from typing import Any, Literal

import httpx

from tp_mcp.client import TPClient, WorkoutCreateRequest, parse_workout_detail, parse_workout_list

# Mapping from user-facing sport name to TP API workoutTypeValueId (family ID)
SPORT_TO_FAMILY_ID: dict[str, int] = {
    "Swim": 1,
    "Bike": 2,
    "Run": 3,
    "Brick": 4,
    "Crosstrain": 5,
    "Race": 6,
    "DayOff": 7,
    "MTB": 8,
    "Strength": 29,
    "Custom": 10,
    "XCSkiing": 11,
    "Rowing": 12,
    "Walk": 13,
    "Other": 100,
}
VALID_SPORTS = set(SPORT_TO_FAMILY_ID.keys())
# Reverse mapping for display
FAMILY_ID_TO_SPORT: dict[int, str] = {v: k for k, v in SPORT_TO_FAMILY_ID.items()}
FILE_DATA_DIR = Path(tempfile.gettempdir()) / "tp-mcp" / "files"


def _validate_structured_workout(structured_workout: dict[str, Any]) -> str | None:
    """Validate the minimum schema needed to round-trip structured workouts."""
    required = {
        "structure",
        "polyline",
        "primaryLengthMetric",
        "primaryIntensityMetric",
        "primaryIntensityTargetOrRange",
    }
    missing = required - set(structured_workout.keys())
    if missing:
        return f"structured_workout is missing required fields: {', '.join(sorted(missing))}"
    if not isinstance(structured_workout.get("structure"), list):
        return "structured_workout.structure must be a list."
    return None


def _encode_workout_structure(structured_workout: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Encode workout structure as JSON string for TP write endpoints."""
    if structured_workout is None:
        return None, None

    error = _validate_structured_workout(structured_workout)
    if error:
        return None, error

    try:
        return json.dumps(structured_workout, separators=(",", ":")), None
    except (TypeError, ValueError) as e:
        return None, f"structured_workout must be JSON-serializable: {e}"


def _decode_workout_structure(raw_structure: Any) -> dict[str, Any] | None:
    """Decode workout structure from TP read responses."""
    if raw_structure is None:
        return None
    if isinstance(raw_structure, dict):
        return raw_structure
    if isinstance(raw_structure, str):
        try:
            parsed = json.loads(raw_structure)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            return None
    return None


def _is_numeric_id(value: str, *, allow_negative: bool = False) -> bool:
    """Return True when value is a numeric ID string."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if allow_negative:
        return text.lstrip("-").isdigit()
    return text.isdigit()


def _extract_file_infos(raw_data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Normalize TP workout file metadata arrays."""
    infos = raw_data.get(key)
    if not isinstance(infos, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in infos:
        if not isinstance(item, dict):
            continue
        file_id = item.get("fileId")
        normalized.append(
            {
                "file_id": str(file_id) if file_id is not None else None,
                "file_system_id": item.get("fileSystemId"),
                "file_name": item.get("fileName"),
                "uploaded_at": item.get("dateUploaded"),
            }
        )
    return normalized


def _gzip_if_needed(file_bytes: bytes) -> bytes:
    """Ensure upload payload uses gzip bytes as expected by TP filedata endpoint."""
    if len(file_bytes) >= 2 and file_bytes[0] == 0x1F and file_bytes[1] == 0x8B:
        return file_bytes
    return gzip.compress(file_bytes)


def _parse_content_disposition_filename(value: str | None) -> str | None:
    """Extract filename from Content-Disposition header."""
    if not value:
        return None
    lower = value.lower()
    token = "filename="
    idx = lower.find(token)
    if idx == -1:
        return None
    filename = value[idx + len(token):].strip().strip('"').strip("'")
    return Path(filename).name if filename else None


def _normalize_workout_day(workout_day: str) -> str:
    """Convert YYYY-MM-DD to TP datetime format, pass through if already datetime."""
    value = workout_day.strip()
    if "T" in value:
        return value
    return f"{value}T00:00:00"


def _save_workout_file(workout_id: str, file_id: str, filename: str, data: bytes) -> str:
    """Persist downloaded workout file and return absolute path."""
    FILE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    fallback_name = f"workout_{workout_id}_file_{file_id}.fit.gz"
    safe_name = Path(filename).name if filename else fallback_name
    path = FILE_DATA_DIR / safe_name
    path.write_bytes(data)
    return str(path.resolve())


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
            raw_data = response.data if isinstance(response.data, dict) else {}
            workout = parse_workout_detail(response.data)
            structured_workout = _decode_workout_structure(raw_data.get("structure"))

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
                "structured_workout": structured_workout,
                "device_files": _extract_file_infos(raw_data, "workoutDeviceFileInfos"),
                "attachment_files": _extract_file_infos(raw_data, "attachmentFileInfos"),
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
    structured_workout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new planned workout.

    Args:
        date: Workout date in ISO format (YYYY-MM-DD).
        sport: Sport type (Bike, Run, Swim, Brick, Crosstrain, Race, DayOff, MTB, Strength, Custom, XCSkiing, Rowing, Walk, Other).
        title: Workout title.
        description: Optional workout description.
        coach_comments: Optional coach notes.
        duration_planned: Planned duration in seconds.
        distance_planned: Planned distance in meters.
        tss_planned: Planned Training Stress Score (>= 0).
        if_planned: Planned Intensity Factor (0.0 - 1.5).
        workout_type: Optional workout type value ID.
        structured_workout: Structured workout payload from TP workout builder format.

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

    structure_payload, structure_error = _encode_workout_structure(structured_workout)
    if structure_error:
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": structure_error}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        family_id = SPORT_TO_FAMILY_ID[sport]
        request = WorkoutCreateRequest(
            workoutDay=date,
            workoutTypeValueId=workout_type if workout_type is not None else family_id,
            title=title,
            description=description,
            coachComments=coach_comments,
            totalTimePlanned=duration_planned,
            distancePlanned=distance_planned,
            tssPlanned=tss_planned,
            ifPlanned=if_planned,
        )
        payload = request.to_api_payload()
        if structure_payload is not None:
            payload["structure"] = structure_payload
        payload["athleteId"] = athlete_id  # required by API

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts"
        response = await client.post(endpoint, json=payload)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        data = response.data or {}
        returned_family_id = data.get("workoutTypeValueId")
        returned_sport = FAMILY_ID_TO_SPORT.get(returned_family_id, sport) if returned_family_id else sport
        return {
            "id": str(data.get("workoutId", "")),
            "date": data.get("workoutDay", date),
            "title": data.get("title", title),
            "sport": returned_sport,
            "metrics": {
                "duration_planned": data.get("totalTimePlanned") * 3600 if data.get("totalTimePlanned") is not None else None,
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
    structured_workout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update an existing planned workout.

    Args:
        workout_id: The workout ID to update.
        date: New date in ISO format (YYYY-MM-DD).
        sport: New sport type (Bike, Run, Swim, Brick, Crosstrain, Race, DayOff, MTB, Strength, Custom, XCSkiing, Rowing, Walk, Other).
        title: New title.
        description: New description.
        coach_comments: New coach notes.
        duration_planned: New planned duration in seconds.
        distance_planned: New planned distance in meters.
        tss_planned: New planned TSS (>= 0).
        if_planned: New planned IF (0.0 - 1.5).
        workout_type: New workout type value ID.
        structured_workout: Structured workout payload from TP workout builder format.

    Returns:
        Dict with updated workout details.
    """
    # Validate workout_id
    if not workout_id or not str(workout_id).strip().lstrip("-").isdigit():
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "workout_id must be a numeric ID."}

    # Require at least one field
    update_fields = [
        date,
        sport,
        title,
        description,
        coach_comments,
        duration_planned,
        distance_planned,
        tss_planned,
        if_planned,
        workout_type,
        structured_workout,
    ]
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

    structure_payload, structure_error = _encode_workout_structure(structured_workout)
    if structure_error:
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": structure_error}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        # 1. Fetch current workout to ensure a full payload for PUT (Read-Modify-Write)
        get_endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}"
        get_response = await client.get(get_endpoint)
        if get_response.is_error:
            return {
                "isError": True,
                "error_code": get_response.error_code.value if get_response.error_code else "API_ERROR",
                "message": f"Failed to fetch workout for update: {get_response.message}",
            }
        
        payload = get_response.data.copy() if get_response.data else {}
        
        # 2. Update fields in payload
        if date is not None:
            payload["workoutDay"] = date
        if sport is not None:
            payload["workoutTypeValueId"] = SPORT_TO_FAMILY_ID[sport]
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if coach_comments is not None:
            payload["coachComments"] = coach_comments
        if duration_planned is not None:
            # Convert to decimal hours for API
            payload["totalTimePlanned"] = float(duration_planned) / 3600
        if distance_planned is not None:
            payload["distancePlanned"] = distance_planned
        if tss_planned is not None:
            payload["tssPlanned"] = tss_planned
        if if_planned is not None:
            payload["ifPlanned"] = if_planned
        if workout_type is not None:
            payload["workoutTypeValueId"] = workout_type
        if structure_payload is not None:
            payload["structure"] = structure_payload
            
        payload["athleteId"] = athlete_id  # ensure athleteId is present

        # 3. Send PUT request with full payload
        response = await client.put(get_endpoint, json=payload)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        data = response.data or {}
        returned_family_id = data.get("workoutTypeValueId") or payload.get("workoutTypeValueId")
        returned_sport = FAMILY_ID_TO_SPORT.get(returned_family_id, str(returned_family_id)) if returned_family_id else None
        return {
            "id": str(data.get("workoutId", workout_id)),
            "date": data.get("workoutDay", payload.get("workoutDay")),
            "title": data.get("title", payload.get("title")),
            "sport": returned_sport,
            "metrics": {
                "duration_planned": data.get("totalTimePlanned", payload.get("totalTimePlanned")) * 3600 if (data.get("totalTimePlanned") is not None or payload.get("totalTimePlanned") is not None) else None,
                "distance_planned": data.get("distancePlanned", payload.get("distancePlanned")),
                "tss_planned": data.get("tssPlanned", payload.get("tssPlanned")),
                "if_planned": data.get("ifPlanned", payload.get("ifPlanned")),
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
    if not _is_numeric_id(workout_id):
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


async def tp_upload_workout_file(
    workout_id: str,
    file_path: str | None = None,
    file_data_base64: str | None = None,
    workout_day: str | None = None,
) -> dict[str, Any]:
    """Upload a workout file to an existing workout.

    Upload payload follows TP API's filedata endpoint format:
    {"workoutDay":"YYYY-MM-DDT00:00:00","data":"<base64(gzip(bytes))>"}
    """
    if not _is_numeric_id(workout_id):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "workout_id must be a numeric ID."}
    if not file_path and not file_data_base64:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Provide either file_path or file_data_base64.",
        }
    if file_path and file_data_base64:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Provide only one of file_path or file_data_base64.",
        }

    raw_bytes: bytes
    if file_path:
        try:
            raw_bytes = Path(file_path).read_bytes()
        except OSError as e:
            return {
                "isError": True,
                "error_code": "VALIDATION_ERROR",
                "message": f"Could not read file_path: {e}",
            }
    else:
        try:
            raw_bytes = base64.b64decode(file_data_base64 or "", validate=True)
        except (ValueError, TypeError) as e:
            return {
                "isError": True,
                "error_code": "VALIDATION_ERROR",
                "message": f"file_data_base64 is invalid base64: {e}",
            }

    if not raw_bytes:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Uploaded file content must not be empty.",
        }

    gzipped = _gzip_if_needed(raw_bytes)
    payload_data = base64.b64encode(gzipped).decode("ascii")

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        resolved_workout_day: str
        if workout_day:
            resolved_workout_day = _normalize_workout_day(workout_day)
        else:
            get_endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}"
            get_response = await client.get(get_endpoint)
            if get_response.is_error:
                return {
                    "isError": True,
                    "error_code": get_response.error_code.value if get_response.error_code else "API_ERROR",
                    "message": f"Failed to fetch workout for upload: {get_response.message}",
                }
            workout_payload = get_response.data if isinstance(get_response.data, dict) else {}
            existing_day = workout_payload.get("workoutDay")
            if not existing_day:
                return {
                    "isError": True,
                    "error_code": "API_ERROR",
                    "message": "Could not determine workoutDay for upload. Provide workout_day explicitly.",
                }
            resolved_workout_day = _normalize_workout_day(str(existing_day))

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}/filedata"
        response = await client.post(endpoint, json={"workoutDay": resolved_workout_day, "data": payload_data})

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        resp_data = response.data if isinstance(response.data, dict) else {}
        return {
            "workout_id": str(resp_data.get("workoutId", workout_id)),
            "uploaded_bytes": len(raw_bytes),
            "uploaded_gzip_bytes": len(gzipped),
            "workout_day": resolved_workout_day,
            "message": "Workout file uploaded successfully.",
        }


async def tp_download_workout_file(
    workout_id: str,
    file_id: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Download a workout file by file_id from TP rawfiledata endpoint."""
    if not _is_numeric_id(workout_id):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "workout_id must be a numeric ID."}
    if not _is_numeric_id(file_id, allow_negative=True):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "file_id must be a numeric ID (can be negative)."}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        token_result = await client._ensure_access_token()
        if not token_result.success:
            return {
                "isError": True,
                "error_code": token_result.error_code.value if token_result.error_code else "AUTH_INVALID",
                "message": token_result.message or "Failed to obtain access token.",
            }

        await client._ensure_client()
        await client._throttle()
        assert client._client is not None

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}/rawfiledata/{file_id}"
        url = f"{client.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {client._token_cache.access_token}", "Accept": "*/*"}

        try:
            response = await client._client.request("GET", url=url, headers=headers)
        except httpx.TimeoutException:
            return {"isError": True, "error_code": "NETWORK_ERROR", "message": "Request timed out. Check your network connection."}
        except httpx.RequestError as e:
            return {"isError": True, "error_code": "NETWORK_ERROR", "message": f"Network error: {e}"}

        if response.status_code == 401:
            return {
                "isError": True,
                "error_code": "AUTH_EXPIRED",
                "message": "Session expired or invalid. Run 'tp-mcp auth' to re-authenticate.",
            }
        if response.status_code == 404:
            return {"isError": True, "error_code": "NOT_FOUND", "message": f"Workout file {file_id} not found."}
        if response.status_code != 200:
            return {
                "isError": True,
                "error_code": "API_ERROR",
                "message": f"API error: {response.status_code} - {response.text}",
            }

        filename = _parse_content_disposition_filename(response.headers.get("Content-Disposition"))
        content = response.content
        if output_path:
            target = Path(output_path)
            if target.exists() and target.is_dir():
                save_name = filename or f"workout_{workout_id}_file_{file_id}.fit.gz"
                file_out = (target / Path(save_name).name).resolve()
            else:
                file_out = target.resolve()
            file_out.parent.mkdir(parents=True, exist_ok=True)
            file_out.write_bytes(content)
            saved_to = str(file_out)
        else:
            saved_to = _save_workout_file(
                workout_id=workout_id,
                file_id=file_id,
                filename=filename or "",
                data=content,
            )

        return {
            "workout_id": workout_id,
            "file_id": file_id,
            "file_name": filename,
            "content_type": response.headers.get("Content-Type"),
            "size_bytes": len(content),
            "saved_to": saved_to,
            "message": "Workout file downloaded successfully.",
        }


async def tp_delete_workout_file(workout_id: str, file_id: str) -> dict[str, Any]:
    """Delete a workout file by file_id."""
    if not _is_numeric_id(workout_id):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "workout_id must be a numeric ID."}
    if not _is_numeric_id(file_id, allow_negative=True):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "file_id must be a numeric ID (can be negative)."}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not get athlete ID. Re-authenticate."}

        endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}/filedata/{file_id}"
        response = await client.delete(endpoint)
        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        return {"workout_id": workout_id, "file_id": file_id, "message": "Workout file deleted successfully."}
