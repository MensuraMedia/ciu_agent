"""Tier 2 full-canvas analysis via the Claude API.

Sends a complete screenshot to the Claude vision API and receives a
structured description of every interactive zone on the screen.  This is
the most expensive analysis tier and should only fire when the frame-diff
engine detects a large change (>30 % pixel delta or application switch).

Dependencies: ``models.zone``, ``config.settings``, ``httpx``,
``base64``, ``json`` (stdlib), and optionally ``cv2`` / ``numpy`` for
frame encoding.

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.tier2_analyzer import (
        Tier2Analyzer,
        Tier2Request,
    )

    settings = get_default_settings()
    analyzer = Tier2Analyzer(settings, api_key="sk-ant-...")

    request = Tier2Request(
        image_data=png_bytes,
        screen_width=1920,
        screen_height=1080,
        context="User just switched to the browser.",
    )
    response = await analyzer.analyze(request)
    for zone in response.zones:
        print(zone.id, zone.label, zone.bounds)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

import httpx
import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.models.zone import (
    Rectangle,
    Zone,
    ZoneState,
    ZoneType,
)

logger = logging.getLogger(__name__)

# Anthropic Messages API endpoint.
_API_URL: str = "https://api.anthropic.com/v1/messages"

# Model used for vision analysis.
_MODEL: str = "claude-sonnet-4-20250514"

# Default max tokens for the API response.
_MAX_TOKENS: int = 4096

# Anthropic API version header.
_API_VERSION: str = "2023-06-01"

# ------------------------------------------------------------------
# System prompt that instructs Claude to return structured zone data.
# ------------------------------------------------------------------
_SYSTEM_PROMPT: str = (
    "You are a UI analysis engine.  You receive a screenshot of a "
    "computer screen and must identify every interactive or visually "
    "distinct element.  Return ONLY a JSON array (no markdown, no "
    "commentary).  Each element in the array is an object with:\n"
    "\n"
    '  "label"  : string  -- visible text or short description\n'
    '  "type"   : string  -- one of: button, text_field, link, '
    "dropdown, checkbox, slider, menu_item, tab, scroll_area, "
    "static, unknown\n"
    '  "state"  : string  -- one of: enabled, disabled, focused, '
    "hovered, pressed, checked, unchecked, expanded, collapsed, "
    "unknown\n"
    '  "bounds" : object  -- {x, y, width, height} in pixels, '
    "origin top-left\n"
    '  "parent" : string | null  -- label of the enclosing '
    "container zone, or null if top-level\n"
    "\n"
    "Guidelines:\n"
    "- Coordinates must be in absolute screen pixels.\n"
    "- Include menus, toolbars, status bars, and content panes.\n"
    "- Nest child elements under their visual parent.\n"
    "- If unsure about type or state, use 'unknown'.\n"
    "- Return [] if the screen is blank or unreadable.\n"
)


# ------------------------------------------------------------------
# Request / Response data classes
# ------------------------------------------------------------------


@dataclass
class Tier2Request:
    """A request to analyse a full screenshot via the Claude API.

    Attributes:
        image_data: PNG-encoded image bytes.
        screen_width: Width of the captured screen in pixels.
        screen_height: Height of the captured screen in pixels.
        context: Optional human-readable context about what changed
            since the last analysis (e.g. "App switch detected").
    """

    image_data: bytes
    screen_width: int
    screen_height: int
    context: str = ""


@dataclass
class Tier2Response:
    """Response from a Tier 2 analysis call.

    Attributes:
        zones: Detected interactive zones parsed from the API
            response.
        raw_response: The raw text content returned by the API.
        latency_ms: Round-trip time of the API call in milliseconds.
        token_count: Approximate total tokens consumed (input +
            output) as reported by the API usage field.
        success: Whether the call completed without error.
        error: Human-readable error string; empty on success.
    """

    zones: list[Zone] = field(default_factory=list)
    raw_response: str = ""
    latency_ms: float = 0.0
    token_count: int = 0
    success: bool = False
    error: str = ""


# ------------------------------------------------------------------
# Analyser
# ------------------------------------------------------------------


class Tier2Analyzer:
    """Sends screenshots to the Claude API for full zone detection.

    This is the most expensive analysis tier.  It should only be
    triggered when the screen changes substantially (>30 % pixels
    changed or application switch detected).

    The analyser is fully self-contained: it builds the prompt,
    calls the API, parses the response, and returns typed ``Zone``
    objects.  All configuration is injected via the ``Settings``
    dataclass -- there is no global state.
    """

    def __init__(
        self,
        settings: Settings,
        api_key: str = "",
    ) -> None:
        """Initialise with settings and optional API key.

        Args:
            settings: Application settings controlling timeouts,
                retry counts, and back-off parameters.
            api_key: Anthropic API key.  If empty, the value of the
                ``ANTHROPIC_API_KEY`` environment variable is used.
                A missing key is not an error at construction time
                (useful for tests), but ``analyze`` will fail.
        """
        self._settings = settings
        self._api_key: str = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    # -- Prompt construction ----------------------------------------

    def build_prompt(self, request: Tier2Request) -> dict:
        """Build the Claude Messages API payload for zone analysis.

        Returns a ``dict`` ready to be serialised to JSON and sent to
        ``/v1/messages``.  The payload uses the Anthropic vision
        format with a base64-encoded PNG image.

        Args:
            request: The analysis request containing the screenshot
                and screen dimensions.

        Returns:
            A dictionary matching the Anthropic Messages API schema.
        """
        b64_image: str = base64.b64encode(request.image_data).decode("ascii")

        user_text = (
            f"Screen dimensions: {request.screen_width}x"
            f"{request.screen_height} pixels.\n"
            "Identify every interactive and visually distinct UI "
            "element.  Return the JSON array described in the system "
            "prompt."
        )
        if request.context:
            user_text += f"\n\nContext: {request.context}"

        payload: dict = {
            "model": _MODEL,
            "max_tokens": _MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64_image,
                            },
                        },
                        {
                            "type": "text",
                            "text": user_text,
                        },
                    ],
                }
            ],
        }
        return payload

    # -- Response parsing -------------------------------------------

    def parse_response(self, response_text: str) -> list[Zone]:
        """Parse the Claude JSON response into ``Zone`` objects.

        The parser handles three common formats:
        1. A bare JSON array: ``[ {...}, ... ]``
        2. A JSON object wrapping an array: ``{"zones": [...]}``
        3. JSON embedded in a Markdown code block:
           ````` ```json ... ``` `````

        If parsing fails the method logs the error and returns an
        empty list -- it never raises.

        Args:
            response_text: Raw text content from the API response.

        Returns:
            A list of ``Zone`` instances.  May be empty on failure.
        """
        cleaned = self._extract_json(response_text)
        if not cleaned:
            logger.error("Tier2: unable to locate JSON in API response")
            return []

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("Tier2: JSON decode failed: %s", exc)
            return []

        # Normalise to a list of dicts.
        items: list[dict]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "zones" in data:
            items = data["zones"]
        else:
            logger.error(
                "Tier2: unexpected JSON structure: %s",
                type(data).__name__,
            )
            return []

        zones: list[Zone] = []
        for idx, item in enumerate(items):
            try:
                zone = self._item_to_zone(item, idx)
                zones.append(zone)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Tier2: skipping zone item %d: %s", idx, exc)
        return zones

    # -- Async analysis ---------------------------------------------

    async def analyze(self, request: Tier2Request) -> Tier2Response:
        """Send a screenshot to the Claude API and return zones.

        Implements retry with exponential back-off per the settings.
        On success the ``Tier2Response.success`` flag is ``True`` and
        ``zones`` is populated.  On failure ``success`` is ``False``
        and ``error`` contains a description.

        Args:
            request: The analysis request with PNG image data.

        Returns:
            A ``Tier2Response`` with detected zones and metadata.
        """
        if not self._api_key:
            return Tier2Response(
                success=False,
                error="No API key configured.",
            )

        payload = self.build_prompt(request)
        headers = self._build_headers()
        timeout = httpx.Timeout(
            self._settings.api_timeout_vision_seconds,
            connect=10.0,
        )

        last_error = ""
        retries = self._settings.api_max_retries

        for attempt in range(retries):
            start_ns = time.monotonic_ns()
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                ) as client:
                    http_resp = await client.post(
                        _API_URL,
                        headers=headers,
                        json=payload,
                    )
                elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000

                if http_resp.status_code == 200:
                    return self._handle_success(http_resp, elapsed_ms)

                last_error = f"HTTP {http_resp.status_code}: {http_resp.text[:200]}"
                logger.warning(
                    "Tier2: attempt %d/%d failed: %s",
                    attempt + 1,
                    retries,
                    last_error,
                )

                # Only retry on transient server errors.
                if http_resp.status_code < 500:
                    break

            except httpx.HTTPError as exc:
                elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Tier2: attempt %d/%d error: %s",
                    attempt + 1,
                    retries,
                    last_error,
                )

            # Exponential back-off before next attempt.
            if attempt < retries - 1:
                delay = self._settings.api_backoff_base_seconds * (2**attempt)
                import asyncio

                await asyncio.sleep(delay)

        return Tier2Response(
            success=False,
            error=last_error,
            latency_ms=elapsed_ms,
        )

    # -- Synchronous wrapper ----------------------------------------

    def analyze_sync(self, request: Tier2Request) -> Tier2Response:
        """Synchronous version of ``analyze``.  Blocks until done.

        Uses a plain ``httpx`` synchronous client.  Retry logic
        mirrors the async path.

        Args:
            request: The analysis request with PNG image data.

        Returns:
            A ``Tier2Response`` with detected zones and metadata.
        """
        if not self._api_key:
            return Tier2Response(
                success=False,
                error="No API key configured.",
            )

        payload = self.build_prompt(request)
        headers = self._build_headers()
        timeout = httpx.Timeout(
            self._settings.api_timeout_vision_seconds,
            connect=10.0,
        )

        last_error = ""
        elapsed_ms = 0.0
        retries = self._settings.api_max_retries

        for attempt in range(retries):
            start_ns = time.monotonic_ns()
            try:
                with httpx.Client(timeout=timeout) as client:
                    http_resp = client.post(
                        _API_URL,
                        headers=headers,
                        json=payload,
                    )
                elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000

                if http_resp.status_code == 200:
                    return self._handle_success(http_resp, elapsed_ms)

                last_error = f"HTTP {http_resp.status_code}: {http_resp.text[:200]}"
                logger.warning(
                    "Tier2: sync attempt %d/%d failed: %s",
                    attempt + 1,
                    retries,
                    last_error,
                )

                if http_resp.status_code < 500:
                    break

            except httpx.HTTPError as exc:
                elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Tier2: sync attempt %d/%d error: %s",
                    attempt + 1,
                    retries,
                    last_error,
                )

            if attempt < retries - 1:
                time.sleep(self._settings.api_backoff_base_seconds * (2**attempt))

        return Tier2Response(
            success=False,
            error=last_error,
            latency_ms=elapsed_ms,
        )

    # -- Frame encoding ---------------------------------------------

    @staticmethod
    def encode_frame(frame: NDArray[np.uint8]) -> bytes:
        """Encode a BGR NumPy frame to PNG bytes.

        This is a convenience helper for callers that hold a raw
        capture frame (as produced by ``CaptureEngine``) and need to
        convert it to the PNG bytes expected by ``Tier2Request``.

        Args:
            frame: An ``(H, W, 3)`` BGR ``uint8`` NumPy array as
                returned by OpenCV / the capture engine.

        Returns:
            PNG-encoded image bytes.

        Raises:
            RuntimeError: If OpenCV fails to encode the frame.
        """
        import cv2  # noqa: E402 — lazy import avoids hard dependency

        success, buffer = cv2.imencode(".png", frame)
        if not success:
            raise RuntimeError("cv2.imencode failed to encode frame as PNG")
        return bytes(buffer)

    # -- Enum mappers -----------------------------------------------

    @staticmethod
    def _map_zone_type(type_str: str) -> ZoneType:
        """Map a string zone type to the ``ZoneType`` enum.

        Performs a case-insensitive lookup.  Returns
        ``ZoneType.UNKNOWN`` for unrecognised strings.

        Args:
            type_str: Type name from the API response.

        Returns:
            The matching ``ZoneType`` member.
        """
        normalised = type_str.strip().lower()
        for member in ZoneType:
            if member.value == normalised:
                return member
        return ZoneType.UNKNOWN

    @staticmethod
    def _map_zone_state(state_str: str) -> ZoneState:
        """Map a string zone state to the ``ZoneState`` enum.

        Performs a case-insensitive lookup.  Returns
        ``ZoneState.UNKNOWN`` for unrecognised strings.

        Args:
            state_str: State name from the API response.

        Returns:
            The matching ``ZoneState`` member.
        """
        normalised = state_str.strip().lower()
        for member in ZoneState:
            if member.value == normalised:
                return member
        return ZoneState.UNKNOWN

    # -- Private helpers --------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for the Anthropic Messages API.

        Returns:
            A dict of header name-value pairs.
        """
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    def _handle_success(
        self,
        http_resp: httpx.Response,
        elapsed_ms: float,
    ) -> Tier2Response:
        """Extract zones and metadata from a successful API response.

        Args:
            http_resp: The ``httpx.Response`` with status 200.
            elapsed_ms: Request round-trip time in milliseconds.

        Returns:
            A populated ``Tier2Response``.
        """
        body = http_resp.json()

        # Extract text from the first content block.
        raw_text = ""
        for block in body.get("content", []):
            if block.get("type") == "text":
                raw_text = block.get("text", "")
                break

        # Token usage (input_tokens + output_tokens).
        usage = body.get("usage", {})
        token_count = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        zones = self.parse_response(raw_text)

        return Tier2Response(
            zones=zones,
            raw_response=raw_text,
            latency_ms=elapsed_ms,
            token_count=token_count,
            success=True,
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract a JSON payload from raw response text.

        Handles:
        - Bare JSON (starts with ``[`` or ``{``).
        - JSON wrapped in a Markdown fenced code block.

        Args:
            text: Raw text that may contain JSON.

        Returns:
            The extracted JSON string, or an empty string if no
            JSON could be found.
        """
        stripped = text.strip()

        # Try bare JSON first.
        if stripped.startswith("[") or stripped.startswith("{"):
            return stripped

        # Try Markdown code block: ```json ... ``` or ``` ... ```
        pattern = r"```(?:json)?\s*\n?(.*?)```"
        match = re.search(pattern, stripped, re.DOTALL)
        if match:
            return match.group(1).strip()

        return ""

    def _item_to_zone(self, item: dict, index: int) -> Zone:
        """Convert a single parsed JSON dict to a ``Zone``.

        Args:
            item: A dictionary with keys ``label``, ``type``,
                ``state``, ``bounds``, and optionally ``parent``.
            index: Ordinal position used to generate a fallback id.

        Returns:
            A ``Zone`` instance.

        Raises:
            KeyError: If required keys are missing.
            TypeError: If values have the wrong type.
            ValueError: If bounds contain invalid numbers.
        """
        bounds_data = item["bounds"]
        bounds = Rectangle(
            x=int(bounds_data["x"]),
            y=int(bounds_data["y"]),
            width=int(bounds_data["width"]),
            height=int(bounds_data["height"]),
        )

        label: str = str(item.get("label", f"zone_{index}"))
        zone_type = self._map_zone_type(str(item.get("type", "unknown")))
        zone_state = self._map_zone_state(str(item.get("state", "unknown")))

        # Generate a stable id from the label or a UUID fallback.
        zone_id: str = item.get("id", "")
        if not zone_id:
            safe_label = re.sub(r"[^a-z0-9]", "_", label.lower())
            zone_id = f"{safe_label}_{index}"

        parent_id: str | None = item.get("parent") or None

        return Zone(
            id=zone_id,
            bounds=bounds,
            type=zone_type,
            label=label,
            state=zone_state,
            parent_id=parent_id,
            confidence=1.0,
            last_seen=time.time(),
        )
