"""Unit tests for the Tier 2 vision analyzer.

Tests cover prompt construction, response parsing (multiple JSON formats),
zone-type/state enum mapping, synchronous analysis with mocked httpx,
frame encoding, and error handling (no API key, HTTP errors, retries).

All HTTP traffic is mocked -- no real API calls are made.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from ciu_agent.config.settings import Settings, get_default_settings
from ciu_agent.core.tier2_analyzer import Tier2Analyzer, Tier2Request, Tier2Response
from ciu_agent.models.zone import Rectangle, ZoneState, ZoneType

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Settings:
    """Return a Settings with fast timeouts for testing."""
    defaults = {
        "api_timeout_vision_seconds": 5.0,
        "api_max_retries": 3,
        "api_backoff_base_seconds": 0.0,  # no delay in tests
    }
    defaults.update(overrides)
    return Settings.from_dict(defaults)


def _make_request(context: str = "") -> Tier2Request:
    """Return a minimal Tier2Request with 1x1 PNG bytes."""
    # A trivial non-empty byte string is sufficient; the analyser just
    # base64-encodes whatever it receives.
    return Tier2Request(
        image_data=b"\x89PNG_FAKE",
        screen_width=1920,
        screen_height=1080,
        context=context,
    )


def _make_zone_dict(
    label: str = "OK",
    zone_type: str = "button",
    state: str = "enabled",
    x: int = 10,
    y: int = 20,
    w: int = 80,
    h: int = 30,
    parent: str | None = None,
) -> dict:
    """Return a single zone dict as the API would return it."""
    d: dict[str, Any] = {
        "label": label,
        "type": zone_type,
        "state": state,
        "bounds": {"x": x, "y": y, "width": w, "height": h},
    }
    if parent is not None:
        d["parent"] = parent
    return d


def _make_api_response_body(
    zones_text: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> dict:
    """Build a dict matching the Anthropic Messages API 200 shape."""
    return {
        "content": [
            {"type": "text", "text": zones_text},
        ],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def _mock_httpx_response(
    status_code: int = 200,
    json_body: dict | None = None,
    text: str = "",
) -> MagicMock:
    """Create a mock that quacks like an httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or json.dumps(json_body or {})
    resp.json.return_value = json_body or {}
    return resp


# ==================================================================
# Test classes
# ==================================================================


class TestBuildPrompt:
    """Tests for Tier2Analyzer.build_prompt."""

    def test_payload_has_required_keys(self) -> None:
        """Payload contains model, max_tokens, system, and messages."""
        analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")
        payload = analyzer.build_prompt(_make_request())

        assert "model" in payload
        assert "max_tokens" in payload
        assert "system" in payload
        assert "messages" in payload

    def test_messages_structure(self) -> None:
        """Messages list has one user message with image and text blocks."""
        analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")
        payload = analyzer.build_prompt(_make_request())

        messages = payload["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

        content = messages[0]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "image"
        assert content[1]["type"] == "text"

    def test_image_is_base64_encoded(self) -> None:
        """The image source data is valid base64 of the input bytes."""
        raw = b"\x89PNG_FAKE_DATA_1234"
        request = Tier2Request(
            image_data=raw,
            screen_width=800,
            screen_height=600,
        )
        analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")
        payload = analyzer.build_prompt(request)

        b64_data = payload["messages"][0]["content"][0]["source"]["data"]
        decoded = base64.b64decode(b64_data)
        assert decoded == raw

    def test_image_media_type_is_png(self) -> None:
        """The image block declares media_type as image/png."""
        analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")
        payload = analyzer.build_prompt(_make_request())

        source = payload["messages"][0]["content"][0]["source"]
        assert source["media_type"] == "image/png"
        assert source["type"] == "base64"

    def test_screen_dimensions_in_text(self) -> None:
        """User text includes the screen width x height."""
        request = Tier2Request(
            image_data=b"x",
            screen_width=2560,
            screen_height=1440,
        )
        analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")
        payload = analyzer.build_prompt(request)

        text = payload["messages"][0]["content"][1]["text"]
        assert "2560x1440" in text

    def test_context_appended_when_provided(self) -> None:
        """When request.context is non-empty it appears in the user text."""
        request = _make_request(context="Browser just opened.")
        analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")
        payload = analyzer.build_prompt(request)

        text = payload["messages"][0]["content"][1]["text"]
        assert "Browser just opened." in text

    def test_context_absent_when_empty(self) -> None:
        """When request.context is empty the 'Context:' label is absent."""
        request = _make_request(context="")
        analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")
        payload = analyzer.build_prompt(request)

        text = payload["messages"][0]["content"][1]["text"]
        assert "Context:" not in text


class TestParseResponse:
    """Tests for Tier2Analyzer.parse_response."""

    def setup_method(self) -> None:
        self.analyzer = Tier2Analyzer(_make_settings(), api_key="test-key")

    def test_bare_json_array(self) -> None:
        """A bare JSON array is parsed into Zone objects."""
        data = [_make_zone_dict(label="Save", zone_type="button")]
        text = json.dumps(data)

        zones = self.analyzer.parse_response(text)
        assert len(zones) == 1
        assert zones[0].label == "Save"
        assert zones[0].type == ZoneType.BUTTON

    def test_wrapped_zones_object(self) -> None:
        """A JSON object with a 'zones' key is unwrapped correctly."""
        data = {"zones": [_make_zone_dict(label="Cancel")]}
        text = json.dumps(data)

        zones = self.analyzer.parse_response(text)
        assert len(zones) == 1
        assert zones[0].label == "Cancel"

    def test_markdown_code_block_json(self) -> None:
        """JSON inside a ```json ... ``` block is extracted."""
        inner = json.dumps([_make_zone_dict(label="Submit")])
        text = f"Here are the zones:\n```json\n{inner}\n```"

        zones = self.analyzer.parse_response(text)
        assert len(zones) == 1
        assert zones[0].label == "Submit"

    def test_markdown_code_block_no_language(self) -> None:
        """JSON inside a bare ``` ... ``` block (no 'json' tag) works."""
        inner = json.dumps([_make_zone_dict(label="Open")])
        text = f"```\n{inner}\n```"

        zones = self.analyzer.parse_response(text)
        assert len(zones) == 1
        assert zones[0].label == "Open"

    def test_invalid_json_returns_empty(self) -> None:
        """Malformed JSON returns an empty list, not an exception."""
        zones = self.analyzer.parse_response("{not valid json!!")
        assert zones == []

    def test_empty_string_returns_empty(self) -> None:
        """An empty response string returns an empty list."""
        zones = self.analyzer.parse_response("")
        assert zones == []

    def test_plain_text_no_json_returns_empty(self) -> None:
        """Plain text with no JSON structure returns empty list."""
        zones = self.analyzer.parse_response("I found some buttons on screen.")
        assert zones == []

    def test_unexpected_json_structure_returns_empty(self) -> None:
        """A dict without a 'zones' key returns empty list."""
        text = json.dumps({"elements": [{"label": "X"}]})
        zones = self.analyzer.parse_response(text)
        assert zones == []

    def test_missing_bounds_skips_item(self) -> None:
        """An item missing the 'bounds' key is skipped gracefully."""
        data = [{"label": "NoBounds", "type": "button", "state": "enabled"}]
        zones = self.analyzer.parse_response(json.dumps(data))
        assert len(zones) == 0

    def test_partial_data_skips_bad_items(self) -> None:
        """Mix of valid and invalid items: only valid ones are kept."""
        good = _make_zone_dict(label="Good")
        bad = {"label": "Bad"}  # no bounds
        data = [good, bad]

        zones = self.analyzer.parse_response(json.dumps(data))
        assert len(zones) == 1
        assert zones[0].label == "Good"

    def test_multiple_zones_parsed(self) -> None:
        """All valid zones in an array are returned."""
        data = [
            _make_zone_dict(label="A", x=0, y=0),
            _make_zone_dict(label="B", x=100, y=100),
            _make_zone_dict(label="C", x=200, y=200),
        ]
        zones = self.analyzer.parse_response(json.dumps(data))
        assert len(zones) == 3
        labels = {z.label for z in zones}
        assert labels == {"A", "B", "C"}

    def test_zone_bounds_are_correct(self) -> None:
        """Parsed zone bounds match the input values."""
        data = [_make_zone_dict(x=50, y=60, w=120, h=40)]
        zones = self.analyzer.parse_response(json.dumps(data))
        assert zones[0].bounds == Rectangle(x=50, y=60, width=120, height=40)

    def test_parent_id_is_set(self) -> None:
        """The parent_id field is populated from the 'parent' key."""
        data = [_make_zone_dict(label="Child", parent="Toolbar")]
        zones = self.analyzer.parse_response(json.dumps(data))
        assert zones[0].parent_id == "Toolbar"

    def test_parent_id_none_when_absent(self) -> None:
        """parent_id is None when 'parent' key is missing."""
        data = [_make_zone_dict()]
        zones = self.analyzer.parse_response(json.dumps(data))
        assert zones[0].parent_id is None

    def test_empty_array_returns_no_zones(self) -> None:
        """An empty JSON array [] yields an empty zone list."""
        zones = self.analyzer.parse_response("[]")
        assert zones == []


class TestMapZoneType:
    """Tests for Tier2Analyzer._map_zone_type."""

    @pytest.mark.parametrize(
        "input_str, expected",
        [
            ("button", ZoneType.BUTTON),
            ("text_field", ZoneType.TEXT_FIELD),
            ("link", ZoneType.LINK),
            ("dropdown", ZoneType.DROPDOWN),
            ("checkbox", ZoneType.CHECKBOX),
            ("slider", ZoneType.SLIDER),
            ("menu_item", ZoneType.MENU_ITEM),
            ("tab", ZoneType.TAB),
            ("scroll_area", ZoneType.SCROLL_AREA),
            ("static", ZoneType.STATIC),
            ("unknown", ZoneType.UNKNOWN),
        ],
    )
    def test_known_types(self, input_str: str, expected: ZoneType) -> None:
        """All defined ZoneType values map correctly."""
        assert Tier2Analyzer._map_zone_type(input_str) == expected

    def test_case_insensitive(self) -> None:
        """Mapping is case-insensitive."""
        assert Tier2Analyzer._map_zone_type("BUTTON") == ZoneType.BUTTON
        assert Tier2Analyzer._map_zone_type("Text_Field") == ZoneType.TEXT_FIELD

    def test_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped before matching."""
        assert Tier2Analyzer._map_zone_type("  link  ") == ZoneType.LINK

    def test_unrecognised_returns_unknown(self) -> None:
        """An unrecognised string maps to ZoneType.UNKNOWN."""
        assert Tier2Analyzer._map_zone_type("widget") == ZoneType.UNKNOWN
        assert Tier2Analyzer._map_zone_type("") == ZoneType.UNKNOWN


class TestMapZoneState:
    """Tests for Tier2Analyzer._map_zone_state."""

    @pytest.mark.parametrize(
        "input_str, expected",
        [
            ("enabled", ZoneState.ENABLED),
            ("disabled", ZoneState.DISABLED),
            ("focused", ZoneState.FOCUSED),
            ("hovered", ZoneState.HOVERED),
            ("pressed", ZoneState.PRESSED),
            ("checked", ZoneState.CHECKED),
            ("unchecked", ZoneState.UNCHECKED),
            ("expanded", ZoneState.EXPANDED),
            ("collapsed", ZoneState.COLLAPSED),
            ("unknown", ZoneState.UNKNOWN),
        ],
    )
    def test_known_states(self, input_str: str, expected: ZoneState) -> None:
        """All defined ZoneState values map correctly."""
        assert Tier2Analyzer._map_zone_state(input_str) == expected

    def test_case_insensitive(self) -> None:
        """Mapping is case-insensitive."""
        assert Tier2Analyzer._map_zone_state("ENABLED") == ZoneState.ENABLED
        assert Tier2Analyzer._map_zone_state("Focused") == ZoneState.FOCUSED

    def test_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped before matching."""
        assert Tier2Analyzer._map_zone_state(" hovered ") == ZoneState.HOVERED

    def test_unrecognised_returns_unknown(self) -> None:
        """An unrecognised string maps to ZoneState.UNKNOWN."""
        assert Tier2Analyzer._map_zone_state("active") == ZoneState.UNKNOWN
        assert Tier2Analyzer._map_zone_state("") == ZoneState.UNKNOWN


class TestEncodeFrame:
    """Tests for Tier2Analyzer.encode_frame (static method)."""

    def test_encodes_valid_frame(self) -> None:
        """A valid BGR uint8 numpy array produces non-empty PNG bytes."""
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        result = Tier2Analyzer.encode_frame(frame)

        assert isinstance(result, bytes)
        assert len(result) > 0
        # PNG magic bytes: \x89PNG
        assert result[:4] == b"\x89PNG"

    def test_encodes_coloured_frame(self) -> None:
        """A frame with actual colour data produces valid PNG bytes."""
        frame = np.full((50, 60, 3), (0, 128, 255), dtype=np.uint8)
        result = Tier2Analyzer.encode_frame(frame)
        assert result[:4] == b"\x89PNG"


class TestNoApiKey:
    """Tests for behaviour when no API key is configured."""

    def test_analyze_sync_no_key_returns_error(self) -> None:
        """analyze_sync returns success=False when no key is set."""
        with patch.dict("os.environ", {}, clear=True):
            # Ensure ANTHROPIC_API_KEY is also absent from env.
            analyzer_no_env = Tier2Analyzer(_make_settings(), api_key="")
        response = analyzer_no_env.analyze_sync(_make_request())

        assert response.success is False
        assert "API key" in response.error or "api key" in response.error.lower()

    def test_analyze_async_no_key_returns_error(self) -> None:
        """analyze (async) returns success=False when no key is set."""
        import asyncio

        with patch.dict("os.environ", {}, clear=True):
            analyzer_no_env = Tier2Analyzer(_make_settings(), api_key="")
        response = asyncio.run(analyzer_no_env.analyze(_make_request()))

        assert response.success is False
        assert "API key" in response.error or "api key" in response.error.lower()


class TestAnalyzeSync:
    """Tests for Tier2Analyzer.analyze_sync with mocked httpx."""

    def _patch_client(self, mock_response: MagicMock) -> Any:
        """Return a context-manager patch for httpx.Client.post."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        return patch("httpx.Client", return_value=mock_client)

    def test_success_returns_zones(self) -> None:
        """A 200 response with valid zones produces success=True."""
        zone_json = json.dumps([_make_zone_dict(label="OK")])
        body = _make_api_response_body(zone_json, 200, 80)
        mock_resp = _mock_httpx_response(200, body)

        analyzer = Tier2Analyzer(_make_settings(), api_key="sk-test")
        with self._patch_client(mock_resp):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is True
        assert len(result.zones) == 1
        assert result.zones[0].label == "OK"
        assert result.token_count == 280  # 200 + 80
        assert result.latency_ms >= 0

    def test_success_raw_response_captured(self) -> None:
        """raw_response contains the text from the API content block."""
        zone_text = json.dumps([_make_zone_dict()])
        body = _make_api_response_body(zone_text)
        mock_resp = _mock_httpx_response(200, body)

        analyzer = Tier2Analyzer(_make_settings(), api_key="sk-test")
        with self._patch_client(mock_resp):
            result = analyzer.analyze_sync(_make_request())

        assert result.raw_response == zone_text

    def test_http_400_does_not_retry(self) -> None:
        """A 4xx error is not retried (only 5xx triggers retries)."""
        mock_resp = _mock_httpx_response(400, text="Bad request")

        settings = _make_settings(api_max_retries=3)
        analyzer = Tier2Analyzer(settings, api_key="sk-test")

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is False
        assert "400" in result.error
        # Only 1 call -- no retries for client errors.
        assert mock_client.post.call_count == 1

    def test_http_500_retries(self) -> None:
        """A 500 error is retried up to api_max_retries times."""
        mock_resp = _mock_httpx_response(500, text="Internal Server Error")

        settings = _make_settings(api_max_retries=3)
        analyzer = Tier2Analyzer(settings, api_key="sk-test")

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is False
        assert "500" in result.error
        assert mock_client.post.call_count == 3

    def test_network_error_retries(self) -> None:
        """An httpx.ConnectError triggers retries."""
        settings = _make_settings(api_max_retries=2)
        analyzer = Tier2Analyzer(settings, api_key="sk-test")

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with patch("httpx.Client", return_value=mock_client):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is False
        assert "ConnectError" in result.error
        assert mock_client.post.call_count == 2

    def test_timeout_error_retries(self) -> None:
        """An httpx.ReadTimeout triggers retries."""
        settings = _make_settings(api_max_retries=2)
        analyzer = Tier2Analyzer(settings, api_key="sk-test")

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ReadTimeout("timed out")

        with patch("httpx.Client", return_value=mock_client):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is False
        assert "ReadTimeout" in result.error
        assert mock_client.post.call_count == 2

    def test_retry_then_success(self) -> None:
        """First attempt fails (500), second succeeds (200)."""
        fail_resp = _mock_httpx_response(500, text="Overloaded")

        zone_json = json.dumps([_make_zone_dict(label="Retry Win")])
        ok_body = _make_api_response_body(zone_json)
        ok_resp = _mock_httpx_response(200, ok_body)

        settings = _make_settings(api_max_retries=3)
        analyzer = Tier2Analyzer(settings, api_key="sk-test")

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [fail_resp, ok_resp]

        with patch("httpx.Client", return_value=mock_client):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is True
        assert len(result.zones) == 1
        assert result.zones[0].label == "Retry Win"
        assert mock_client.post.call_count == 2

    def test_headers_contain_api_key(self) -> None:
        """The request sends the api key in x-api-key header."""
        zone_json = json.dumps([])
        body = _make_api_response_body(zone_json)
        mock_resp = _mock_httpx_response(200, body)

        analyzer = Tier2Analyzer(_make_settings(), api_key="sk-secret-123")

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            analyzer.analyze_sync(_make_request())

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["x-api-key"] == "sk-secret-123"

    def test_empty_zones_from_api(self) -> None:
        """An API response with an empty array produces 0 zones."""
        body = _make_api_response_body("[]")
        mock_resp = _mock_httpx_response(200, body)

        analyzer = Tier2Analyzer(_make_settings(), api_key="sk-test")
        with self._patch_client(mock_resp):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is True
        assert result.zones == []


class TestTier2RequestDataclass:
    """Tests for the Tier2Request dataclass."""

    def test_default_context_is_empty(self) -> None:
        """context defaults to an empty string."""
        req = Tier2Request(
            image_data=b"img",
            screen_width=800,
            screen_height=600,
        )
        assert req.context == ""

    def test_fields_stored(self) -> None:
        """All fields are stored on construction."""
        req = Tier2Request(
            image_data=b"png",
            screen_width=1024,
            screen_height=768,
            context="hello",
        )
        assert req.image_data == b"png"
        assert req.screen_width == 1024
        assert req.screen_height == 768
        assert req.context == "hello"


class TestTier2ResponseDataclass:
    """Tests for the Tier2Response dataclass."""

    def test_defaults(self) -> None:
        """Default response has empty zones, no error, success=False."""
        resp = Tier2Response()
        assert resp.zones == []
        assert resp.raw_response == ""
        assert resp.latency_ms == 0.0
        assert resp.token_count == 0
        assert resp.success is False
        assert resp.error == ""

    def test_custom_values(self) -> None:
        """Custom values are preserved."""
        resp = Tier2Response(
            zones=[],
            raw_response="raw",
            latency_ms=42.5,
            token_count=999,
            success=True,
            error="",
        )
        assert resp.latency_ms == 42.5
        assert resp.token_count == 999
        assert resp.success is True


class TestApiKeyFromEnv:
    """Tests that the analyzer reads ANTHROPIC_API_KEY from the environment."""

    def test_env_key_used_when_param_empty(self) -> None:
        """If api_key param is empty, ANTHROPIC_API_KEY env var is used."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-from-env"}):
            analyzer = Tier2Analyzer(_make_settings(), api_key="")
        # Access the private key to verify (acceptable in tests).
        assert analyzer._api_key == "sk-from-env"

    def test_param_overrides_env(self) -> None:
        """If api_key param is provided it takes precedence over env."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-env"}):
            analyzer = Tier2Analyzer(_make_settings(), api_key="sk-param")
        assert analyzer._api_key == "sk-param"

    def test_no_key_anywhere(self) -> None:
        """If no key anywhere the internal key is empty string."""
        with patch.dict("os.environ", {}, clear=True):
            analyzer = Tier2Analyzer(_make_settings(), api_key="")
        assert analyzer._api_key == ""


class TestSettingsIntegration:
    """Tests that Settings fields are respected by the analyzer."""

    def test_default_settings_work(self) -> None:
        """The analyzer can be constructed with get_default_settings()."""
        settings = get_default_settings()
        analyzer = Tier2Analyzer(settings, api_key="sk-test")
        assert analyzer._settings is settings

    def test_custom_retry_count_respected(self) -> None:
        """api_max_retries from Settings controls retry attempts."""
        mock_resp = _mock_httpx_response(500, text="error")
        settings = _make_settings(api_max_retries=5)
        analyzer = Tier2Analyzer(settings, api_key="sk-test")

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            result = analyzer.analyze_sync(_make_request())

        assert result.success is False
        assert mock_client.post.call_count == 5


class TestExtractJsonEdgeCases:
    """Additional tests for the _extract_json static method."""

    def test_whitespace_around_json(self) -> None:
        """Leading/trailing whitespace is tolerated."""
        text = "   [{}]   "
        result = Tier2Analyzer._extract_json(text)
        assert result == "[{}]"

    def test_code_block_with_extra_text(self) -> None:
        """JSON in a code block preceded by commentary is extracted."""
        text = (
            "Here is the result:\n"
            "```json\n"
            '[{"label":"X","bounds":{"x":0,"y":0,"width":1,"height":1}}]\n'
            "```\n"
            "That's all."
        )
        result = Tier2Analyzer._extract_json(text)
        assert result.startswith("[")

    def test_bare_object_detected(self) -> None:
        """A bare JSON object (not array) is detected."""
        text = '{"zones": []}'
        result = Tier2Analyzer._extract_json(text)
        assert result == '{"zones": []}'
