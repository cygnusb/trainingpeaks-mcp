"""Tests for workout tools."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from tp_mcp.client.http import APIResponse, ErrorCode
from tp_mcp.tools.workouts import tp_create_workout, tp_delete_workout, tp_get_workout, tp_get_workouts, tp_update_workout


class TestTpGetWorkouts:
    """Tests for tp_get_workouts tool."""

    @pytest.mark.asyncio
    async def test_get_workouts_success(self, mock_api_responses):
        """Test successful workout retrieval."""
        user_response = APIResponse(
            success=True, data={"user": {"personId": 123}}
        )
        workouts_response = APIResponse(
            success=True, data=mock_api_responses["workouts"]
        )

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(
                side_effect=[user_response, workouts_response]
            )
            mock_instance.athlete_id = None
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await tp_get_workouts("2025-01-08", "2025-01-09")

        assert "isError" not in result or not result.get("isError")
        assert result["count"] == 2
        assert len(result["workouts"]) == 2

    @pytest.mark.asyncio
    async def test_get_workouts_filter_completed(self, mock_api_responses):
        """Test filtering for completed workouts only."""
        user_response = APIResponse(
            success=True, data={"user": {"personId": 123}}
        )
        workouts_response = APIResponse(
            success=True, data=mock_api_responses["workouts"]
        )

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(
                side_effect=[user_response, workouts_response]
            )
            mock_instance.athlete_id = None
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await tp_get_workouts(
                "2025-01-08", "2025-01-09", workout_filter="completed"
            )

        assert result["count"] == 1
        assert result["workouts"][0]["type"] == "completed"

    @pytest.mark.asyncio
    async def test_get_workouts_invalid_dates(self):
        """Test with invalid date format."""
        result = await tp_get_workouts("invalid", "2025-01-09")

        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_get_workouts_date_order_error(self):
        """Test with start date after end date."""
        result = await tp_get_workouts("2025-01-10", "2025-01-09")

        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_get_workouts_date_range_too_large(self):
        """Test with date range exceeding 90 days."""
        result = await tp_get_workouts("2025-01-01", "2025-06-01")

        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "90 days" in result["message"]

    @pytest.mark.asyncio
    async def test_get_workouts_date_range_at_limit(self, mock_api_responses):
        """Test with date range exactly at 90 days."""
        user_response = APIResponse(
            success=True, data={"user": {"personId": 123}}
        )
        workouts_response = APIResponse(success=True, data=[])

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(
                side_effect=[user_response, workouts_response]
            )
            mock_instance.athlete_id = None
            mock_client.return_value.__aenter__.return_value = mock_instance

            # 90 days exactly should work
            result = await tp_get_workouts("2025-01-01", "2025-04-01")

        assert "isError" not in result or not result.get("isError")


class TestTpGetWorkout:
    """Tests for tp_get_workout tool."""

    @pytest.mark.asyncio
    async def test_get_workout_success(self, mock_api_responses):
        """Test successful single workout retrieval."""
        user_response = APIResponse(
            success=True, data={"user": {"personId": 123}}
        )
        workout_response = APIResponse(
            success=True, data=mock_api_responses["workout_detail"]
        )

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(
                side_effect=[user_response, workout_response]
            )
            mock_instance.athlete_id = None
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await tp_get_workout("1001")

        assert "isError" not in result or not result.get("isError")
        assert result["id"] == "1001"
        assert result["title"] == "Test Workout"
        assert result["metrics"]["avg_power"] == 200

    @pytest.mark.asyncio
    async def test_get_workout_not_found(self):
        """Test workout not found."""
        user_response = APIResponse(
            success=True, data={"user": {"personId": 123}}
        )
        workout_response = APIResponse(
            success=False,
            error_code=ErrorCode.NOT_FOUND,
            message="Not found",
        )

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(
                side_effect=[user_response, workout_response]
            )
            mock_instance.athlete_id = None
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await tp_get_workout("9999")

        assert result["isError"] is True
        assert result["error_code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_workout_includes_structured_workout(self, mock_api_responses):
        """Structured workout payload is returned when present in API response."""
        user_response = APIResponse(success=True, data={"user": {"personId": 123}})
        workout_data = dict(mock_api_responses["workout_detail"])
        workout_data["structure"] = {"structure": [], "polyline": [], "primaryLengthMetric": "duration", "primaryIntensityMetric": "percentOfFtp", "primaryIntensityTargetOrRange": "range"}
        workout_response = APIResponse(success=True, data=workout_data)

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=[user_response, workout_response])
            mock_instance.athlete_id = None
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await tp_get_workout("1001")

        assert "isError" not in result or not result.get("isError")
        assert result["structured_workout"] == workout_data["structure"]


def _mock_client_with_athlete(mock_client_cls, **method_responses):
    """Helper: configure a mock TPClient with ensure_athlete_id=123 and given HTTP methods."""
    mock_instance = AsyncMock()
    mock_instance.ensure_athlete_id = AsyncMock(return_value=123)
    for method_name, return_value in method_responses.items():
        setattr(mock_instance, method_name, AsyncMock(return_value=return_value))
    mock_client_cls.return_value.__aenter__.return_value = mock_instance
    return mock_instance


class TestTpCreateWorkout:
    """Tests for tp_create_workout tool."""

    @pytest.mark.asyncio
    async def test_create_workout_success(self):
        """Test successful workout creation."""
        created = APIResponse(
            success=True,
            data={
                "workoutId": 9001,
                "workoutDay": "2026-03-10",
                "title": "Morning Ride",
                "workoutTypeValueId": 2,  # Bike family ID
                "totalTimePlanned": 1.0, # 1.0 hour = 3600 seconds
                "tssPlanned": 80.0,
            },
        )
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock = _mock_client_with_athlete(mock_client, post=created)
            result = await tp_create_workout(
                date="2026-03-10", sport="Bike", title="Morning Ride",
                duration_planned=3600, tss_planned=80.0,
            )

        assert "isError" not in result or not result.get("isError")
        assert result["id"] == "9001"
        assert result["title"] == "Morning Ride"
        assert result["sport"] == "Bike"
        assert result["metrics"]["duration_planned"] == 3600
        assert result["metrics"]["tss_planned"] == 80.0
        assert result["message"] == "Workout created successfully."

    @pytest.mark.asyncio
    async def test_create_workout_payload_camelcase(self):
        """Test that payload uses camelCase and excludes None fields."""
        captured_payload = {}

        async def capture_post(endpoint, json=None):
            captured_payload.update(json or {})
            return APIResponse(success=True, data={"workoutId": 1, "workoutDay": "2026-03-10", "title": "X", "workoutTypeValueId": 3})

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=123)
            mock_instance.post = capture_post
            mock_client.return_value.__aenter__.return_value = mock_instance

            await tp_create_workout(date="2026-03-10", sport="Run", title="X", duration_planned=3600, tss_planned=50.0)

        assert "workoutDay" in captured_payload
        assert "workoutTypeValueId" in captured_payload
        assert captured_payload["workoutTypeValueId"] == 3  # Run family ID
        assert "tssPlanned" in captured_payload
        assert captured_payload["totalTimePlanned"] == 1.0 # 3600s / 3600
        # None fields must be absent
        assert "description" not in captured_payload
        assert "coachComments" not in captured_payload
        assert "distancePlanned" not in captured_payload

    @pytest.mark.asyncio
    async def test_create_workout_payload_structure_serialized(self):
        """Structured workout is serialized as JSON string for TP API."""
        captured_payload = {}
        structured_workout = {
            "structure": [],
            "polyline": [],
            "primaryLengthMetric": "duration",
            "primaryIntensityMetric": "percentOfFtp",
            "primaryIntensityTargetOrRange": "range",
        }

        async def capture_post(endpoint, json=None):
            captured_payload.update(json or {})
            return APIResponse(success=True, data={"workoutId": 1, "workoutDay": "2026-03-10", "title": "X", "workoutTypeValueId": 3})

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=123)
            mock_instance.post = capture_post
            mock_client.return_value.__aenter__.return_value = mock_instance

            await tp_create_workout(
                date="2026-03-10",
                sport="Run",
                title="X",
                structured_workout=structured_workout,
            )

        assert isinstance(captured_payload["structure"], str)
        assert json.loads(captured_payload["structure"]) == structured_workout

    @pytest.mark.asyncio
    async def test_create_workout_invalid_structured_payload(self):
        """Missing required structure keys should be rejected."""
        result = await tp_create_workout(
            date="2026-03-10",
            sport="Run",
            title="X",
            structured_workout={"structure": []},
        )
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "structured_workout" in result["message"]

    @pytest.mark.asyncio
    async def test_create_workout_invalid_date(self):
        """Test validation of invalid date format."""
        result = await tp_create_workout(date="not-a-date", sport="Run", title="Test")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "date" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_workout_invalid_sport(self):
        """Test validation of unsupported sport."""
        result = await tp_create_workout(date="2026-03-10", sport="Surfing", title="Test")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "sport" in result["message"].lower() or "Surfing" in result["message"]

    @pytest.mark.asyncio
    async def test_create_workout_empty_title(self):
        """Test validation of empty title."""
        result = await tp_create_workout(date="2026-03-10", sport="Run", title="   ")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "title" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_workout_if_out_of_range(self):
        """Test validation of IF outside 0-1.5."""
        result = await tp_create_workout(date="2026-03-10", sport="Bike", title="X", if_planned=2.0)
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "if_planned" in result["message"]

    @pytest.mark.asyncio
    async def test_create_workout_negative_tss(self):
        """Test validation of negative TSS."""
        result = await tp_create_workout(date="2026-03-10", sport="Run", title="X", tss_planned=-10)
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "tss_planned" in result["message"]

    @pytest.mark.asyncio
    async def test_create_workout_api_auth_error(self):
        """Test API auth error propagation."""
        auth_err = APIResponse(success=False, error_code=ErrorCode.AUTH_INVALID, message="Auth invalid")
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            _mock_client_with_athlete(mock_client, post=auth_err)
            result = await tp_create_workout(date="2026-03-10", sport="Run", title="X")
        assert result["isError"] is True
        assert result["error_code"] == "AUTH_INVALID"

    @pytest.mark.asyncio
    async def test_create_workout_athlete_id_failure(self):
        """Test handling when athlete ID cannot be fetched."""
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=None)
            mock_client.return_value.__aenter__.return_value = mock_instance
            result = await tp_create_workout(date="2026-03-10", sport="Run", title="X")
        assert result["isError"] is True
        assert result["error_code"] == "AUTH_INVALID"


class TestTpUpdateWorkout:
    """Tests for tp_update_workout tool."""

    @pytest.mark.asyncio
    async def test_update_workout_success(self):
        """Test successful workout update."""
        current = APIResponse(
            success=True,
            data={
                "workoutId": 1001,
                "workoutDay": "2026-03-10",
                "title": "Old Title",
                "workoutTypeValueId": 2,  # Bike family ID
            },
        )
        updated = APIResponse(
            success=True,
            data={
                "workoutId": 1001,
                "workoutDay": "2026-03-10",
                "title": "Updated Ride",
                "workoutTypeValueId": 2,  # Bike family ID
                "tssPlanned": 100.0,
            },
        )
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=123)
            mock_instance.get = AsyncMock(return_value=current)
            mock_instance.put = AsyncMock(return_value=updated)
            mock_client.return_value.__aenter__.return_value = mock_instance
            result = await tp_update_workout(workout_id="1001", title="Updated Ride", tss_planned=100.0)

        assert "isError" not in result or not result.get("isError")
        assert result["id"] == "1001"
        assert result["title"] == "Updated Ride"
        assert result["message"] == "Workout updated successfully."

    @pytest.mark.asyncio
    async def test_update_workout_payload_exclude_none(self):
        """Test that update payload merges new fields onto fetched workout fields."""
        captured_payload = {}
        current = APIResponse(
            success=True,
            data={"workoutId": 1001, "workoutDay": "2026-03-10", "workoutTypeValueId": 2},
        )

        async def capture_put(endpoint, json=None):
            captured_payload.update(json or {})
            return APIResponse(success=True, data={"workoutId": 1001})

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=123)
            mock_instance.get = AsyncMock(return_value=current)
            mock_instance.put = capture_put
            mock_client.return_value.__aenter__.return_value = mock_instance

            await tp_update_workout(workout_id="1001", title="New Title")

        assert "title" in captured_payload
        assert captured_payload["title"] == "New Title"
        # Fields from the fetched workout are preserved
        assert captured_payload["workoutDay"] == "2026-03-10"
        assert "tssPlanned" not in captured_payload

    @pytest.mark.asyncio
    async def test_update_workout_no_fields(self):
        """Test that updating with no fields is rejected."""
        result = await tp_update_workout(workout_id="1001")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "field" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_update_workout_invalid_id(self):
        """Test validation of non-numeric workout ID."""
        result = await tp_update_workout(workout_id="abc", title="X")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "numeric" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_update_workout_invalid_sport(self):
        """Test validation of invalid sport in update."""
        result = await tp_update_workout(workout_id="1001", sport="Surfing")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_update_workout_invalid_date(self):
        """Test validation of invalid date in update."""
        result = await tp_update_workout(workout_id="1001", date="bad-date")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_update_workout_not_found(self):
        """Test API not found error when workout does not exist."""
        not_found = APIResponse(success=False, error_code=ErrorCode.NOT_FOUND, message="Not found")
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=123)
            mock_instance.get = AsyncMock(return_value=not_found)
            mock_client.return_value.__aenter__.return_value = mock_instance
            result = await tp_update_workout(workout_id="9999", title="X")
        assert result["isError"] is True
        assert result["error_code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_update_workout_if_out_of_range(self):
        """Test validation of IF outside 0-1.5 in update."""
        result = await tp_update_workout(workout_id="1001", if_planned=1.6)
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_update_workout_negative_tss(self):
        """Test validation of negative TSS in update."""
        result = await tp_update_workout(workout_id="1001", tss_planned=-5)
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_update_workout_structure_serialized(self):
        """Structured workout is serialized as JSON string for update calls."""
        captured_payload = {}
        current = APIResponse(
            success=True,
            data={"workoutId": 1001, "workoutDay": "2026-03-10", "workoutTypeValueId": 2},
        )
        structured_workout = {
            "structure": [],
            "polyline": [],
            "primaryLengthMetric": "duration",
            "primaryIntensityMetric": "percentOfFtp",
            "primaryIntensityTargetOrRange": "range",
        }

        async def capture_put(endpoint, json=None):
            captured_payload.update(json or {})
            return APIResponse(success=True, data={"workoutId": 1001})

        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=123)
            mock_instance.get = AsyncMock(return_value=current)
            mock_instance.put = capture_put
            mock_client.return_value.__aenter__.return_value = mock_instance

            await tp_update_workout(workout_id="1001", structured_workout=structured_workout)

        assert isinstance(captured_payload["structure"], str)
        assert json.loads(captured_payload["structure"]) == structured_workout


class TestTpDeleteWorkout:
    """Tests for tp_delete_workout tool."""

    @pytest.mark.asyncio
    async def test_delete_workout_success(self):
        """Test successful workout deletion."""
        deleted = APIResponse(success=True, data=None)
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            _mock_client_with_athlete(mock_client, delete=deleted)
            result = await tp_delete_workout("1001")

        assert "isError" not in result or not result.get("isError")
        assert "1001" in result["message"]
        assert "deleted" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_workout_invalid_id(self):
        """Test validation of non-numeric workout ID."""
        result = await tp_delete_workout("not-a-number")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "numeric" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_workout_empty_id(self):
        """Test validation of empty workout ID."""
        result = await tp_delete_workout("")
        assert result["isError"] is True
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_delete_workout_not_found(self):
        """Test API not found error on delete."""
        not_found = APIResponse(success=False, error_code=ErrorCode.NOT_FOUND, message="Workout not found")
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            _mock_client_with_athlete(mock_client, delete=not_found)
            result = await tp_delete_workout("9999")
        assert result["isError"] is True
        assert result["error_code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_workout_auth_error(self):
        """Test auth error propagation on delete."""
        auth_err = APIResponse(success=False, error_code=ErrorCode.AUTH_INVALID, message="Auth invalid")
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            _mock_client_with_athlete(mock_client, delete=auth_err)
            result = await tp_delete_workout("1001")
        assert result["isError"] is True
        assert result["error_code"] == "AUTH_INVALID"

    @pytest.mark.asyncio
    async def test_delete_workout_athlete_id_failure(self):
        """Test handling when athlete ID cannot be fetched."""
        with patch("tp_mcp.tools.workouts.TPClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.ensure_athlete_id = AsyncMock(return_value=None)
            mock_client.return_value.__aenter__.return_value = mock_instance
            result = await tp_delete_workout("1001")
        assert result["isError"] is True
        assert result["error_code"] == "AUTH_INVALID"
