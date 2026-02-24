"""Unit tests for the TaskPlanner module.

Tests cover prompt construction, response parsing (multiple JSON formats),
zone summarisation, synchronous planning with mocked httpx, API key handling,
and edge cases for TaskStep/TaskPlan dataclasses.

All HTTP traffic is mocked -- no real API calls are made.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from ciu_agent.config.settings import Settings, get_default_settings
from ciu_agent.core.task_planner import TaskPlanner
from ciu_agent.models.task import TaskPlan, TaskStep
from ciu_agent.models.zone import (
    Rectangle,
    Zone,
    ZoneState,
    ZoneType,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Settings:
    """Return a Settings with fast timeouts for testing."""
    defaults: dict[str, Any] = {
        "api_timeout_text_seconds": 5.0,
        "api_max_retries": 3,
        "api_backoff_base_seconds": 0.0,  # no delay in tests
    }
    defaults.update(overrides)
    return Settings.from_dict(defaults)


def _make_zone(
    zone_id: str = "btn_ok_1",
    label: str = "OK",
    zone_type: ZoneType = ZoneType.BUTTON,
    state: ZoneState = ZoneState.ENABLED,
    x: int = 100,
    y: int = 200,
    width: int = 80,
    height: int = 30,
) -> Zone:
    """Return a Zone with sensible defaults for testing."""
    return Zone(
        id=zone_id,
        bounds=Rectangle(x=x, y=y, width=width, height=height),
        type=zone_type,
        label=label,
        state=state,
    )


def _make_step_dict(
    step_number: int = 1,
    zone_id: str = "btn_ok_1",
    zone_label: str = "OK",
    action_type: str = "click",
    parameters: dict[str, Any] | None = None,
    expected_change: str = "Button pressed",
    description: str = "Click the OK button",
) -> dict[str, Any]:
    """Return a step dict matching the API response format."""
    return {
        "step_number": step_number,
        "zone_id": zone_id,
        "zone_label": zone_label,
        "action_type": action_type,
        "parameters": parameters or {},
        "expected_change": expected_change,
        "description": description,
    }


def _make_api_response_body(
    steps_text: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> dict[str, Any]:
    """Build a dict matching the Anthropic Messages API 200 shape."""
    return {
        "content": [
            {"type": "text", "text": steps_text},
        ],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def _mock_httpx_response(
    status_code: int = 200,
    json_body: dict[str, Any] | None = None,
    text: str = "",
) -> MagicMock:
    """Create a mock that quacks like an httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or json.dumps(json_body or {})
    resp.json.return_value = json_body or {}
    return resp


def _patch_client(mock_response: MagicMock) -> Any:
    """Return a context-manager patch for httpx.Client."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response
    return patch("httpx.Client", return_value=mock_client)


def _make_mock_client(
    response: MagicMock | None = None,
    side_effect: Any = None,
) -> MagicMock:
    """Return a mock httpx.Client with context-manager support."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    if side_effect is not None:
        mock_client.post.side_effect = side_effect
    elif response is not None:
        mock_client.post.return_value = response
    return mock_client


# ==================================================================
# Test classes
# ==================================================================


class TestBuildPrompt:
    """Tests for TaskPlanner.build_prompt."""

    def setup_method(self) -> None:
        self.planner = TaskPlanner(
            _make_settings(), api_key="test-key"
        )

    def test_payload_has_required_keys(self) -> None:
        """Payload contains model, max_tokens, system, messages."""
        payload = self.planner.build_prompt("Open settings", [])

        assert "model" in payload
        assert "max_tokens" in payload
        assert "system" in payload
        assert "messages" in payload

    def test_model_is_string(self) -> None:
        """The model field is a non-empty string."""
        payload = self.planner.build_prompt("Open settings", [])
        assert isinstance(payload["model"], str)
        assert len(payload["model"]) > 0

    def test_max_tokens_is_positive_int(self) -> None:
        """max_tokens is a positive integer."""
        payload = self.planner.build_prompt("Open settings", [])
        assert isinstance(payload["max_tokens"], int)
        assert payload["max_tokens"] > 0

    def test_system_prompt_is_string(self) -> None:
        """system field is a non-empty string."""
        payload = self.planner.build_prompt("Open settings", [])
        assert isinstance(payload["system"], str)
        assert len(payload["system"]) > 0

    def test_messages_contain_task_description(self) -> None:
        """User message includes the task description string."""
        payload = self.planner.build_prompt(
            "Enable dark mode", []
        )
        user_text = payload["messages"][0]["content"][0]["text"]
        assert "Enable dark mode" in user_text

    def test_messages_contain_zone_summary(self) -> None:
        """User message includes zone information."""
        zone = _make_zone(
            zone_id="btn_save_1", label="Save"
        )
        payload = self.planner.build_prompt("Save file", [zone])
        user_text = payload["messages"][0]["content"][0]["text"]
        assert "btn_save_1" in user_text
        assert "Save" in user_text

    def test_zone_summary_includes_details(self) -> None:
        """Zone summary includes id, label, type, state, center."""
        zone = _make_zone(
            zone_id="chk_1",
            label="Remember me",
            zone_type=ZoneType.CHECKBOX,
            state=ZoneState.UNCHECKED,
            x=50,
            y=100,
            width=20,
            height=20,
        )
        payload = self.planner.build_prompt("Check box", [zone])
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "chk_1" in user_text
        assert "Remember me" in user_text
        assert "checkbox" in user_text
        assert "unchecked" in user_text
        # center of (50, 100, 20, 20) is (60, 110)
        assert "(60, 110)" in user_text

    def test_empty_zone_list_works(self) -> None:
        """build_prompt handles an empty zone list without error."""
        payload = self.planner.build_prompt("Do nothing", [])
        user_text = payload["messages"][0]["content"][0]["text"]
        assert "no zones available" in user_text.lower()

    def test_multiple_zones_formatted(self) -> None:
        """Multiple zones are all present in the user message."""
        zones = [
            _make_zone(zone_id="z1", label="Alpha"),
            _make_zone(zone_id="z2", label="Beta"),
            _make_zone(zone_id="z3", label="Gamma"),
        ]
        payload = self.planner.build_prompt("Do things", zones)
        user_text = payload["messages"][0]["content"][0]["text"]

        for z in zones:
            assert z.id in user_text
            assert z.label in user_text

    def test_payload_is_valid_anthropic_format(self) -> None:
        """Payload has the required Anthropic API fields."""
        payload = self.planner.build_prompt("Test", [])

        # Must have model, system, messages at top level.
        assert "model" in payload
        assert "system" in payload
        assert "messages" in payload

        # Messages must be a list with at least one user message.
        assert isinstance(payload["messages"], list)
        assert len(payload["messages"]) >= 1
        assert payload["messages"][0]["role"] == "user"

        # Content block must be a list with type/text entries.
        content = payload["messages"][0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert isinstance(content[0]["text"], str)

    def test_zones_detected_format(self) -> None:
        """User message shows 'Zones detected: N (M clickable)' format."""
        zones = [
            _make_zone(zone_id="btn_1", zone_type=ZoneType.BUTTON),
            _make_zone(
                zone_id="static_1",
                label="Title",
                zone_type=ZoneType.STATIC,
            ),
            _make_zone(
                zone_id="chk_1",
                label="Agree",
                zone_type=ZoneType.CHECKBOX,
            ),
        ]
        payload = self.planner.build_prompt("Do things", zones)
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "Zones detected: 3" in user_text
        # button and checkbox are clickable; static is not
        assert "(2 clickable)" in user_text

    def test_available_zones_heading(self) -> None:
        """User message uses the new 'AVAILABLE ZONES' heading."""
        zone = _make_zone()
        payload = self.planner.build_prompt("Test", [zone])
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "AVAILABLE ZONES (use these zone_ids for visual mode):" in user_text

    def test_reminder_text_present(self) -> None:
        """User message includes the REMINDER about zone_id usage."""
        payload = self.planner.build_prompt(
            "Test", [_make_zone()]
        )
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "REMINDER: You MUST use zone_id" in user_text

    def test_completed_steps_included_in_prompt(self) -> None:
        """build_prompt with completed_steps shows them in prompt."""
        completed = [
            "Clicked the Start button",
            "Typed 'notepad' in search box",
        ]
        payload = self.planner.build_prompt(
            "Open notepad", [], completed_steps=completed
        )
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "ALREADY COMPLETED (DO NOT REPEAT)" in user_text
        assert "Clicked the Start button" in user_text
        assert "Typed 'notepad' in search box" in user_text
        assert "Plan ONLY the remaining steps" in user_text

    def test_completed_steps_numbered(self) -> None:
        """Completed steps are numbered sequentially in the prompt."""
        completed = ["Step A", "Step B", "Step C"]
        payload = self.planner.build_prompt(
            "Task", [], completed_steps=completed
        )
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "1. Step A" in user_text
        assert "2. Step B" in user_text
        assert "3. Step C" in user_text

    def test_no_completed_steps_omits_section(self) -> None:
        """build_prompt without completed_steps has no progress text."""
        payload = self.planner.build_prompt("Open file", [])
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "ALREADY COMPLETED (DO NOT REPEAT)" not in user_text
        assert "Plan ONLY the remaining steps" not in user_text

    def test_completed_steps_none_omits_section(self) -> None:
        """Explicitly passing None omits the progress section."""
        payload = self.planner.build_prompt(
            "Open file", [], completed_steps=None
        )
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "ALREADY COMPLETED (DO NOT REPEAT)" not in user_text

    def test_completed_steps_empty_list_omits_section(self) -> None:
        """An empty completed_steps list omits the progress section."""
        payload = self.planner.build_prompt(
            "Open file", [], completed_steps=[]
        )
        user_text = payload["messages"][0]["content"][0]["text"]

        assert "ALREADY COMPLETED (DO NOT REPEAT)" not in user_text


class TestParseResponse:
    """Tests for TaskPlanner.parse_response."""

    def setup_method(self) -> None:
        self.planner = TaskPlanner(
            _make_settings(), api_key="test-key"
        )

    def test_bare_json_array(self) -> None:
        """A bare JSON array is parsed into TaskStep objects."""
        data = [_make_step_dict(step_number=1, action_type="click")]
        text = json.dumps(data)

        steps = self.planner.parse_response(text)
        assert len(steps) == 1
        assert steps[0].action_type == "click"

    def test_steps_wrapper_object(self) -> None:
        """A JSON object with 'steps' key is unwrapped correctly."""
        data = {"steps": [_make_step_dict(zone_id="btn_1")]}
        text = json.dumps(data)

        steps = self.planner.parse_response(text)
        assert len(steps) == 1
        assert steps[0].zone_id == "btn_1"

    def test_markdown_code_block(self) -> None:
        """JSON inside a ```json ... ``` block is extracted."""
        inner = json.dumps([_make_step_dict(description="Click")])
        text = f"Here is the plan:\n```json\n{inner}\n```"

        steps = self.planner.parse_response(text)
        assert len(steps) == 1
        assert steps[0].description == "Click"

    def test_invalid_json_returns_empty(self) -> None:
        """Malformed JSON returns an empty list, not exception."""
        steps = self.planner.parse_response("{not valid json!!")
        assert steps == []

    def test_empty_string_returns_empty(self) -> None:
        """An empty response string returns an empty list."""
        steps = self.planner.parse_response("")
        assert steps == []

    def test_missing_optional_fields(self) -> None:
        """Steps with only required fields parse correctly."""
        data = [
            {
                "zone_id": "btn_1",
                "action_type": "click",
            }
        ]
        text = json.dumps(data)

        steps = self.planner.parse_response(text)
        assert len(steps) == 1
        assert steps[0].zone_id == "btn_1"
        assert steps[0].action_type == "click"
        # Optional fields get defaults.
        assert steps[0].zone_label == ""
        assert steps[0].expected_change == ""
        assert steps[0].description == ""
        assert steps[0].parameters == {}

    def test_step_fields_mapped_correctly(self) -> None:
        """All fields from JSON are mapped to TaskStep attributes."""
        data = [
            _make_step_dict(
                step_number=3,
                zone_id="txt_search",
                zone_label="Search Box",
                action_type="type_text",
                parameters={"text": "hello"},
                expected_change="Text appears in search box",
                description="Type search query",
            )
        ]
        text = json.dumps(data)

        steps = self.planner.parse_response(text)
        assert len(steps) == 1
        s = steps[0]
        assert s.step_number == 3
        assert s.zone_id == "txt_search"
        assert s.zone_label == "Search Box"
        assert s.action_type == "type_text"
        assert s.parameters == {"text": "hello"}
        assert s.expected_change == "Text appears in search box"
        assert s.description == "Type search query"

    def test_extra_fields_ignored(self) -> None:
        """Extra JSON fields not in TaskStep are ignored."""
        data = [
            {
                "step_number": 1,
                "zone_id": "btn_1",
                "action_type": "click",
                "confidence": 0.95,
                "extra_field": "should be ignored",
            }
        ]
        text = json.dumps(data)

        steps = self.planner.parse_response(text)
        assert len(steps) == 1
        assert steps[0].zone_id == "btn_1"
        # No error raised despite extra fields.

    def test_mixed_valid_invalid_items(self) -> None:
        """Valid items are kept; invalid ones are skipped."""
        data = [
            _make_step_dict(zone_id="good_1"),
            {"bad": "item"},  # missing zone_id and action_type
            _make_step_dict(zone_id="good_2"),
        ]
        text = json.dumps(data)

        steps = self.planner.parse_response(text)
        assert len(steps) == 2
        assert steps[0].zone_id == "good_1"
        assert steps[1].zone_id == "good_2"

    def test_empty_json_array_returns_empty(self) -> None:
        """An empty JSON array [] yields an empty step list."""
        steps = self.planner.parse_response("[]")
        assert steps == []


class TestPlan:
    """Tests for TaskPlanner.plan with mocked httpx."""

    def test_successful_plan(self) -> None:
        """A 200 response with valid steps produces success=True."""
        steps_json = json.dumps([_make_step_dict()])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")
        with _patch_client(mock_resp):
            result = planner.plan("Click OK", [_make_zone()])

        assert result.success is True
        assert len(result.steps) == 1
        assert result.steps[0].action_type == "click"

    def test_steps_populated_from_response(self) -> None:
        """Steps in the plan come from the API response content."""
        step_data = [
            _make_step_dict(step_number=1, action_type="click"),
            _make_step_dict(
                step_number=2,
                action_type="type_text",
                zone_id="txt_1",
            ),
        ]
        steps_json = json.dumps(step_data)
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")
        with _patch_client(mock_resp):
            result = planner.plan("Fill form", [])

        assert len(result.steps) == 2
        assert result.steps[0].action_type == "click"
        assert result.steps[1].action_type == "type_text"

    def test_api_calls_tracked(self) -> None:
        """api_calls_used reflects the number of API calls made."""
        steps_json = json.dumps([_make_step_dict()])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")
        with _patch_client(mock_resp):
            result = planner.plan("Click OK", [])

        assert result.api_calls_used >= 1

    def test_latency_ms_is_set(self) -> None:
        """latency_ms is a non-negative float after a plan call."""
        steps_json = json.dumps([_make_step_dict()])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")
        with _patch_client(mock_resp):
            result = planner.plan("Click OK", [])

        assert isinstance(result.latency_ms, float)
        assert result.latency_ms >= 0

    def test_raw_response_captured(self) -> None:
        """raw_response contains the text from the API content."""
        steps_json = json.dumps([_make_step_dict()])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")
        with _patch_client(mock_resp):
            result = planner.plan("Click OK", [])

        assert result.raw_response == steps_json

    def test_no_api_key_returns_error(self) -> None:
        """plan returns success=False when no API key is set."""
        with patch.dict("os.environ", {}, clear=True):
            planner = TaskPlanner(
                _make_settings(), api_key=""
            )
        result = planner.plan("Click OK", [])

        assert result.success is False
        assert "API key" in result.error or "api key" in result.error.lower()

    def test_http_400_no_retry(self) -> None:
        """A 4xx error is not retried (only 5xx triggers retries)."""
        mock_resp = _mock_httpx_response(400, text="Bad request")

        settings = _make_settings(api_max_retries=3)
        planner = TaskPlanner(settings, api_key="sk-test")

        mock_client = _make_mock_client(response=mock_resp)
        with patch("httpx.Client", return_value=mock_client):
            result = planner.plan("Click OK", [])

        assert result.success is False
        assert "400" in result.error
        # Only 1 call -- no retries for client errors.
        assert mock_client.post.call_count == 1

    def test_http_500_triggers_retry(self) -> None:
        """A 500 error is retried up to api_max_retries times."""
        mock_resp = _mock_httpx_response(
            500, text="Internal Server Error"
        )

        settings = _make_settings(api_max_retries=3)
        planner = TaskPlanner(settings, api_key="sk-test")

        mock_client = _make_mock_client(response=mock_resp)
        with patch("httpx.Client", return_value=mock_client):
            result = planner.plan("Click OK", [])

        assert result.success is False
        assert "500" in result.error
        assert mock_client.post.call_count == 3

    def test_network_error_triggers_retry(self) -> None:
        """An httpx.ConnectError triggers retries."""
        settings = _make_settings(api_max_retries=2)
        planner = TaskPlanner(settings, api_key="sk-test")

        mock_client = _make_mock_client(
            side_effect=httpx.ConnectError("Connection refused")
        )
        with patch("httpx.Client", return_value=mock_client):
            result = planner.plan("Click OK", [])

        assert result.success is False
        assert "ConnectError" in result.error
        assert mock_client.post.call_count == 2

    def test_empty_api_response_returns_empty_steps(self) -> None:
        """An API response with empty array produces empty steps."""
        body = _make_api_response_body("[]")
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")
        with _patch_client(mock_resp):
            result = planner.plan("Impossible task", [])

        assert result.success is True
        assert result.steps == []

    def test_plan_passes_completed_steps_to_build_prompt(self) -> None:
        """plan() forwards completed_steps to build_prompt()."""
        steps_json = json.dumps([_make_step_dict()])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        completed = ["Opened Start menu", "Typed search query"]
        planner = TaskPlanner(_make_settings(), api_key="sk-test")

        with _patch_client(mock_resp) as mock_client_cls:
            result = planner.plan(
                "Launch app", [_make_zone()],
                completed_steps=completed,
            )

        assert result.success is True

        # Verify the prompt sent to the API includes the completed steps.
        call_kwargs = mock_client_cls.return_value.post.call_args
        sent_payload = call_kwargs.kwargs.get(
            "json"
        ) or call_kwargs[1].get("json", {})
        user_text = sent_payload["messages"][0]["content"][0]["text"]

        assert "ALREADY COMPLETED (DO NOT REPEAT)" in user_text
        assert "Opened Start menu" in user_text
        assert "Typed search query" in user_text

    def test_plan_without_completed_steps_omits_progress(self) -> None:
        """plan() without completed_steps omits progress text."""
        steps_json = json.dumps([_make_step_dict()])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")

        with _patch_client(mock_resp) as mock_client_cls:
            result = planner.plan("Click OK", [_make_zone()])

        assert result.success is True

        call_kwargs = mock_client_cls.return_value.post.call_args
        sent_payload = call_kwargs.kwargs.get(
            "json"
        ) or call_kwargs[1].get("json", {})
        user_text = sent_payload["messages"][0]["content"][0]["text"]

        assert "ALREADY COMPLETED (DO NOT REPEAT)" not in user_text


class TestSummarizeZones:
    """Tests for TaskPlanner._summarize_zones."""

    def setup_method(self) -> None:
        self.planner = TaskPlanner(
            _make_settings(), api_key="test-key"
        )

    def test_single_zone_formatted(self) -> None:
        """A single zone is formatted with id, label, type, state."""
        zone = _make_zone(
            zone_id="btn_1",
            label="Submit",
            zone_type=ZoneType.BUTTON,
            state=ZoneState.ENABLED,
        )
        summary = self.planner._summarize_zones([zone])

        assert "btn_1" in summary
        assert "Submit" in summary
        assert "button" in summary
        assert "enabled" in summary

    def test_multiple_zones_all_present(self) -> None:
        """Multiple zones each appear on their own line."""
        zones = [
            _make_zone(zone_id="z1", label="Alpha"),
            _make_zone(zone_id="z2", label="Beta"),
        ]
        summary = self.planner._summarize_zones(zones)

        assert "z1" in summary
        assert "Alpha" in summary
        assert "z2" in summary
        assert "Beta" in summary
        # Should have two lines (one per zone).
        lines = [
            ln for ln in summary.strip().split("\n") if ln.strip()
        ]
        assert len(lines) == 2

    def test_empty_list_returns_message(self) -> None:
        """An empty zone list returns a descriptive string."""
        summary = self.planner._summarize_zones([])
        assert "no zones" in summary.lower()

    def test_center_coordinates_included(self) -> None:
        """Zone center coordinates appear in the summary."""
        zone = _make_zone(x=100, y=200, width=60, height=40)
        # center = (100 + 30, 200 + 20) = (130, 220)
        summary = self.planner._summarize_zones([zone])
        assert "(130, 220)" in summary


class TestEdgeCases:
    """Edge-case tests for TaskPlanner and related dataclasses."""

    def test_api_key_from_environment(self) -> None:
        """If api_key is empty, ANTHROPIC_API_KEY env var is used."""
        with patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "sk-from-env"}
        ):
            planner = TaskPlanner(
                _make_settings(), api_key=""
            )
        assert planner._api_key == "sk-from-env"

    def test_param_key_overrides_env(self) -> None:
        """An explicit api_key parameter overrides the env var."""
        with patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "sk-env"}
        ):
            planner = TaskPlanner(
                _make_settings(), api_key="sk-param"
            )
        assert planner._api_key == "sk-param"

    def test_no_key_anywhere(self) -> None:
        """If no key anywhere the internal key is empty string."""
        with patch.dict("os.environ", {}, clear=True):
            planner = TaskPlanner(
                _make_settings(), api_key=""
            )
        assert planner._api_key == ""

    def test_plan_with_empty_task_still_calls_api(self) -> None:
        """An empty task string still produces an API call."""
        steps_json = json.dumps([])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")

        mock_client = _make_mock_client(response=mock_resp)
        with patch("httpx.Client", return_value=mock_client):
            result = planner.plan("", [])

        assert result.success is True
        assert mock_client.post.call_count == 1

    def test_very_long_zone_list(self) -> None:
        """A large number of zones does not cause errors."""
        zones = [
            _make_zone(
                zone_id=f"zone_{i}",
                label=f"Zone {i}",
                x=i * 10,
                y=i * 5,
            )
            for i in range(200)
        ]
        planner = TaskPlanner(_make_settings(), api_key="sk-test")

        # Just verify prompt builds without error.
        payload = planner.build_prompt("Long zone list", zones)
        user_text = payload["messages"][0]["content"][0]["text"]

        # All zone IDs should be present.
        assert "zone_0" in user_text
        assert "zone_199" in user_text

    def test_task_step_parameters_defaults_to_empty_dict(self) -> None:
        """TaskStep.parameters defaults to an empty dict."""
        step = TaskStep(
            step_number=1,
            zone_id="btn_1",
            zone_label="OK",
            action_type="click",
        )
        assert step.parameters == {}
        assert isinstance(step.parameters, dict)

    def test_task_plan_steps_defaults_to_empty_list(self) -> None:
        """TaskPlan.steps defaults to an empty list."""
        plan = TaskPlan(task_description="Test")
        assert plan.steps == []
        assert isinstance(plan.steps, list)

    def test_retry_then_success(self) -> None:
        """First attempt fails (500), second succeeds (200)."""
        fail_resp = _mock_httpx_response(
            500, text="Overloaded"
        )
        steps_json = json.dumps(
            [_make_step_dict(description="Retry Win")]
        )
        ok_body = _make_api_response_body(steps_json)
        ok_resp = _mock_httpx_response(200, ok_body)

        settings = _make_settings(api_max_retries=3)
        planner = TaskPlanner(settings, api_key="sk-test")

        mock_client = _make_mock_client(
            side_effect=[fail_resp, ok_resp]
        )
        with patch("httpx.Client", return_value=mock_client):
            result = planner.plan("Retry test", [])

        assert result.success is True
        assert len(result.steps) == 1
        assert result.steps[0].description == "Retry Win"
        assert mock_client.post.call_count == 2

    def test_timeout_error_triggers_retry(self) -> None:
        """An httpx.ReadTimeout triggers retries."""
        settings = _make_settings(api_max_retries=2)
        planner = TaskPlanner(settings, api_key="sk-test")

        mock_client = _make_mock_client(
            side_effect=httpx.ReadTimeout("timed out")
        )
        with patch("httpx.Client", return_value=mock_client):
            result = planner.plan("Timeout test", [])

        assert result.success is False
        assert "ReadTimeout" in result.error
        assert mock_client.post.call_count == 2

    def test_task_description_in_plan(self) -> None:
        """The returned TaskPlan carries the original task string."""
        steps_json = json.dumps([])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(_make_settings(), api_key="sk-test")
        with _patch_client(mock_resp):
            result = planner.plan("Open settings tab", [])

        assert result.task_description == "Open settings tab"

    def test_default_settings_work(self) -> None:
        """TaskPlanner can be constructed with get_default_settings."""
        settings = get_default_settings()
        planner = TaskPlanner(settings, api_key="sk-test")
        assert planner._settings is settings

    def test_markdown_code_block_no_language_tag(self) -> None:
        """JSON in a bare ``` ... ``` block (no 'json' tag) works."""
        inner = json.dumps(
            [_make_step_dict(description="Bare block")]
        )
        text = f"```\n{inner}\n```"

        planner = TaskPlanner(
            _make_settings(), api_key="test-key"
        )
        steps = planner.parse_response(text)
        assert len(steps) == 1
        assert steps[0].description == "Bare block"

    def test_plain_text_no_json_returns_empty(self) -> None:
        """Plain text with no JSON structure returns empty list."""
        planner = TaskPlanner(
            _make_settings(), api_key="test-key"
        )
        steps = planner.parse_response(
            "I cannot determine the steps for this task."
        )
        assert steps == []

    def test_unexpected_json_structure_returns_empty(self) -> None:
        """A dict without a 'steps' key returns empty list."""
        planner = TaskPlanner(
            _make_settings(), api_key="test-key"
        )
        text = json.dumps({"actions": [{"zone": "x"}]})
        steps = planner.parse_response(text)
        assert steps == []

    def test_api_calls_used_on_failure(self) -> None:
        """api_calls_used is populated even on failed plans."""
        mock_resp = _mock_httpx_response(
            500, text="Server Error"
        )
        settings = _make_settings(api_max_retries=3)
        planner = TaskPlanner(settings, api_key="sk-test")

        mock_client = _make_mock_client(response=mock_resp)
        with patch("httpx.Client", return_value=mock_client):
            result = planner.plan("Fail test", [])

        assert result.success is False
        assert result.api_calls_used == 3

    def test_headers_contain_api_key(self) -> None:
        """The request sends the API key in x-api-key header."""
        steps_json = json.dumps([])
        body = _make_api_response_body(steps_json)
        mock_resp = _mock_httpx_response(200, body)

        planner = TaskPlanner(
            _make_settings(), api_key="sk-secret-123"
        )

        mock_client = _make_mock_client(response=mock_resp)
        with patch("httpx.Client", return_value=mock_client):
            planner.plan("Header test", [])

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get(
            "headers"
        ) or call_kwargs[1].get("headers", {})
        assert headers["x-api-key"] == "sk-secret-123"
