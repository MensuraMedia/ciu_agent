"""Task planner: decomposes natural language tasks into zone interactions.

Accepts a free-text task description together with the current set of
detected UI zones and produces an ordered list of steps (click, type,
scroll, etc.) that the Brush Controller can execute to accomplish the
task.

The planner calls the Claude API with a text-only prompt (no image).
It follows the same httpx / retry / backoff conventions as
``Tier2Analyzer``.

Dependencies: ``models.zone``, ``config.settings``, ``httpx``,
``json`` (stdlib).

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.task_planner import TaskPlanner

    settings = get_default_settings()
    planner = TaskPlanner(settings, api_key="sk-ant-...")

    zones = registry.get_all()
    plan = planner.plan("Open the Settings tab and enable dark mode", zones)
    for step in plan.steps:
        print(step.step_number, step.description)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import httpx

from ciu_agent.config.settings import Settings
from ciu_agent.models.task import TaskPlan, TaskStep
from ciu_agent.models.zone import Zone

logger = logging.getLogger(__name__)

# Anthropic Messages API endpoint.
_API_URL: str = "https://api.anthropic.com/v1/messages"

# Model used for task planning.
_MODEL: str = "claude-sonnet-4-20250514"

# Max tokens for a plan response (plans are shorter than zone analysis).
_MAX_TOKENS: int = 2048

# Anthropic API version header.
_API_VERSION: str = "2023-06-01"

# ------------------------------------------------------------------
# System prompt that instructs Claude to return a step-by-step plan.
# ------------------------------------------------------------------
_SYSTEM_PROMPT: str = (
    "You are a GUI task execution planner for a desktop automation agent. "
    "Given a task description, OS information, and a list of available UI "
    "zones currently visible on screen, produce a step-by-step plan to "
    "accomplish the task.\n"
    "\n"
    "Return ONLY a JSON array. Each element is an object with:\n"
    '  "step_number": int\n'
    '  "zone_id": string — the ID of the zone to interact with, '
    'or "__global__" for OS-level keyboard/system actions\n'
    '  "zone_label": string — the label for debugging\n'
    '  "action_type": string — one of: click, double_click, '
    "type_text, key_press, scroll\n"
    '  "parameters": object — e.g. {"text": "hello"} or '
    '{"key": "enter"} or {"button": "left"}\n'
    '  "expected_change": string — what should change on screen '
    "after this step\n"
    '  "description": string — human-readable description of what '
    "this step does\n"
    "\n"
    "=== METHODOLOGY ===\n"
    "Follow this sequential methodology when planning:\n"
    "\n"
    "1. EXAMINE THE SCREEN: Look at all available zones to understand "
    "what is currently visible (desktop, application, dialog, etc.).\n"
    "\n"
    "2. IDENTIFY THE ENVIRONMENT: Determine the OS type from the zone "
    "list (Windows taskbar, macOS dock, Linux panel). Use this to "
    "choose the correct keyboard shortcuts and UI conventions.\n"
    "\n"
    "3. LOCATE THE SYSTEM MENU / LAUNCHER: Identify how to access the "
    "OS program launcher:\n"
    "  - Windows: taskbar search, Start menu, or Win+R / Win+S\n"
    "  - macOS: Spotlight (Cmd+Space) or Launchpad\n"
    "  - Linux: application menu or Alt+F2\n"
    "\n"
    "4. ACCESS THE PROGRAM LAUNCHER: If the target application is not "
    "already open, use the appropriate method to reach it:\n"
    "  - Click the Start/Search zone if visible in the zone list\n"
    "  - Use __global__ key_press for keyboard shortcuts\n"
    "\n"
    "5. FIND AND OPEN THE APPLICATION: Search for or navigate to the "
    "desired application. Type the app name, scroll if needed, then "
    "click to open it or press Enter.\n"
    "\n"
    "6. WAIT FOR APPLICATION: After launching, the screen will change. "
    "Include an expected_change describing the new application window.\n"
    "\n"
    "7. OPERATE THE APPLICATION: Interact with the application's menus, "
    "buttons, text fields, and controls in sequential order to achieve "
    "the task. Use zone IDs when the target element is in the zone list. "
    "Use __global__ for keyboard shortcuts within the app.\n"
    "\n"
    "8. COMPLETE THE OPERATION: Perform save, confirm, or close actions "
    "as needed to finalise the task.\n"
    "\n"
    "=== EXECUTION MODES ===\n"
    "The agent supports TWO execution modes. Use BOTH as appropriate:\n"
    "\n"
    "VISUAL MODE (preferred when zones are available):\n"
    "- Use a zone_id from the provided zone list to click, type, or "
    "interact with a visible UI element.\n"
    "- The agent will physically move the mouse cursor to the zone and "
    "perform the action. This provides visual feedback to the user.\n"
    "- ALWAYS prefer visual mode when a matching zone is visible.\n"
    "\n"
    "COMMAND MODE (when no zone is available):\n"
    '- Use zone_id "__global__" with action_type "key_press" or '
    '"type_text" for keyboard shortcuts and text entry.\n'
    "- Use this for OS-level shortcuts, launching apps, or when the "
    "target element has not yet appeared on screen.\n"
    "\n"
    "=== GUIDELINES ===\n"
    "- PREFER VISUAL MODE: If a zone exists for the target element, "
    "use its zone_id so the cursor physically navigates to it.\n"
    "- Use __global__ only when no matching zone is visible.\n"
    "- Common __global__ keyboard shortcuts:\n"
    '  Windows: {"key": "win+r"} (Run dialog), {"key": "win+s"} '
    "(Search), "
    '{"key": "ctrl+s"} (Save), {"key": "alt+f4"} (Close), '
    '{"key": "enter"} (Confirm)\n'
    '  macOS: {"key": "cmd+space"} (Spotlight), {"key": "cmd+s"} '
    "(Save)\n"
    "- For text input: click the target text field zone first (visual "
    "mode), then use type_text on that zone. Only use __global__ "
    "type_text when the field is already focused and no zone exists.\n"
    "- Include expected_change to help verify each step succeeded. The "
    "agent will re-capture the screen and re-detect zones after steps "
    "with significant UI changes.\n"
    "- Keep plans under 20 steps.\n"
    "- IMPORTANT: If the task requires opening an app that is NOT "
    "currently visible, you MUST include steps to find and launch it "
    "first. Do not assume it is already open.\n"
    "- After launching an application, subsequent steps will see NEW "
    "zones from the opened app. Plan to interact with those new zones "
    "using visual mode.\n"
)


# ------------------------------------------------------------------
# Planner
# ------------------------------------------------------------------


class TaskPlanner:
    """Decomposes natural language tasks into zone interaction sequences.

    Sends a text-only prompt to the Claude API describing the task and
    the available zones, then parses the structured JSON response into
    an ordered list of ``TaskStep`` objects.

    All configuration is injected via the ``Settings`` dataclass and
    the API key parameter -- there is no global state.
    """

    def __init__(
        self,
        settings: Settings,
        api_key: str = "",
        platform_name: str = "",
    ) -> None:
        """Initialise with settings and optional API key.

        Args:
            settings: Application settings controlling timeouts,
                retry counts, and back-off parameters.
            api_key: Anthropic API key.  If empty, the value of the
                ``ANTHROPIC_API_KEY`` environment variable is used.
                A missing key is not an error at construction time
                (useful for tests), but ``plan`` will fail.
            platform_name: OS identifier (e.g. ``'windows'``,
                ``'linux'``, ``'macos'``) included in prompts so
                the planner can choose correct shortcuts.
        """
        self._settings = settings
        self._api_key: str = api_key or os.environ.get(
            "ANTHROPIC_API_KEY", ""
        )
        self._platform_name = platform_name

    # -- Zone summarisation ----------------------------------------

    def _summarize_zones(self, zones: list[Zone]) -> str:
        """Format a zone list into a text summary for the prompt.

        Each zone is rendered on a single line with its id, label,
        type, state, and center coordinates.

        Args:
            zones: The zones to summarise.

        Returns:
            A multi-line string describing the available zones.
        """
        if not zones:
            return "(no zones available)"

        lines: list[str] = []
        for zone in zones:
            cx, cy = zone.bounds.center()
            lines.append(
                f"- id={zone.id}  label=\"{zone.label}\"  "
                f"type={zone.type.value}  state={zone.state.value}  "
                f"center=({cx}, {cy})"
            )
        return "\n".join(lines)

    # -- Prompt construction ----------------------------------------

    def build_prompt(self, task: str, zones: list[Zone]) -> dict:
        """Build the Claude Messages API payload for task planning.

        Returns a ``dict`` ready to be serialised to JSON and sent to
        ``/v1/messages``.  The payload is text-only (no images).

        Args:
            task: Natural-language description of the task.
            zones: Currently available UI zones on screen.

        Returns:
            A dictionary matching the Anthropic Messages API schema.
        """
        zone_summary = self._summarize_zones(zones)
        os_line = (
            f"Operating system: {self._platform_name}\n"
            if self._platform_name
            else ""
        )

        user_text = (
            f"Task: {task}\n"
            "\n"
            f"{os_line}"
            f"Number of zones detected: {len(zones)}\n"
            "\n"
            "Available zones on screen:\n"
            f"{zone_summary}\n"
            "\n"
            "Following the methodology in the system prompt, produce "
            "a step-by-step plan to accomplish this task."
        )

        payload: dict = {
            "model": _MODEL,
            "max_tokens": _MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
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

    def parse_response(self, response_text: str) -> list[TaskStep]:
        """Parse the Claude JSON response into ``TaskStep`` objects.

        The parser handles three common formats:

        1. A bare JSON array: ``[ {...}, ... ]``
        2. A JSON object wrapping an array: ``{"steps": [...]}``
        3. JSON embedded in a Markdown code block:
           ````` ```json ... ``` `````

        If parsing fails the method logs the error and returns an
        empty list -- it never raises.

        Args:
            response_text: Raw text content from the API response.

        Returns:
            A list of ``TaskStep`` instances.  May be empty on failure.
        """
        cleaned = self._extract_json(response_text)
        if not cleaned:
            logger.error(
                "TaskPlanner: unable to locate JSON in API response"
            )
            return []

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("TaskPlanner: JSON decode failed: %s", exc)
            return []

        # Normalise to a list of dicts.
        items: list[dict]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "steps" in data:
            items = data["steps"]
        else:
            logger.error(
                "TaskPlanner: unexpected JSON structure: %s",
                type(data).__name__,
            )
            return []

        steps: list[TaskStep] = []
        for idx, item in enumerate(items):
            try:
                step = self._item_to_step(item, idx)
                steps.append(step)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "TaskPlanner: skipping step item %d: %s", idx, exc
                )
        return steps

    # -- Synchronous planning ---------------------------------------

    def plan(self, task: str, zones: list[Zone]) -> TaskPlan:
        """Decompose a task into an ordered list of zone interactions.

        This is a synchronous (blocking) method.  It builds the prompt,
        calls the Claude API with retry and exponential back-off, then
        parses the response into ``TaskStep`` objects.

        Args:
            task: Natural-language description of the task to
                accomplish.
            zones: Currently available UI zones on screen.

        Returns:
            A ``TaskPlan`` describing the steps.  On success the
            ``success`` flag is ``True`` and ``steps`` is populated.
            On failure ``success`` is ``False`` and ``error`` contains
            a description.
        """
        if not self._api_key:
            return TaskPlan(
                task_description=task,
                success=False,
                error="No API key configured.",
            )

        payload = self.build_prompt(task, zones)
        headers = self._build_headers()
        timeout = httpx.Timeout(
            self._settings.api_timeout_text_seconds,
            connect=10.0,
        )

        last_error = ""
        elapsed_ms = 0.0
        retries = self._settings.api_max_retries
        api_calls = 0

        for attempt in range(retries):
            api_calls += 1
            start_ns = time.monotonic_ns()
            try:
                with httpx.Client(timeout=timeout) as client:
                    http_resp = client.post(
                        _API_URL,
                        headers=headers,
                        json=payload,
                    )
                elapsed_ms = (
                    (time.monotonic_ns() - start_ns) / 1_000_000
                )

                if http_resp.status_code == 200:
                    return self._handle_success(
                        http_resp, task, elapsed_ms, api_calls
                    )

                last_error = (
                    f"HTTP {http_resp.status_code}: "
                    f"{http_resp.text[:200]}"
                )
                logger.warning(
                    "TaskPlanner: attempt %d/%d failed: %s",
                    attempt + 1,
                    retries,
                    last_error,
                )

                # Only retry on transient server errors.
                if http_resp.status_code < 500:
                    break

            except httpx.HTTPError as exc:
                elapsed_ms = (
                    (time.monotonic_ns() - start_ns) / 1_000_000
                )
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "TaskPlanner: attempt %d/%d error: %s",
                    attempt + 1,
                    retries,
                    last_error,
                )

            # Exponential back-off before next attempt.
            if attempt < retries - 1:
                delay = self._settings.api_backoff_base_seconds * (
                    2**attempt
                )
                time.sleep(delay)

        return TaskPlan(
            task_description=task,
            success=False,
            error=last_error,
            api_calls_used=api_calls,
            latency_ms=elapsed_ms,
        )

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
        task: str,
        elapsed_ms: float,
        api_calls: int,
    ) -> TaskPlan:
        """Extract steps and metadata from a successful API response.

        Args:
            http_resp: The ``httpx.Response`` with status 200.
            task: The original task description.
            elapsed_ms: Request round-trip time in milliseconds.
            api_calls: Total number of API calls used (with retries).

        Returns:
            A populated ``TaskPlan``.
        """
        body = http_resp.json()

        # Extract text from the first content block.
        raw_text = ""
        for block in body.get("content", []):
            if block.get("type") == "text":
                raw_text = block.get("text", "")
                break

        steps = self.parse_response(raw_text)

        return TaskPlan(
            task_description=task,
            steps=steps,
            raw_response=raw_text,
            success=True,
            api_calls_used=api_calls,
            latency_ms=elapsed_ms,
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

    @staticmethod
    def _item_to_step(item: dict, index: int) -> TaskStep:
        """Convert a single parsed JSON dict to a ``TaskStep``.

        Args:
            item: A dictionary with keys matching the ``TaskStep``
                fields (``step_number``, ``zone_id``, ``zone_label``,
                ``action_type``, ``parameters``, ``expected_change``,
                ``description``).
            index: Ordinal position used as a fallback step number.

        Returns:
            A ``TaskStep`` instance.

        Raises:
            KeyError: If required keys are missing.
            TypeError: If values have the wrong type.
            ValueError: If values are invalid.
        """
        return TaskStep(
            step_number=int(item.get("step_number", index + 1)),
            zone_id=str(item["zone_id"]),
            zone_label=str(item.get("zone_label", "")),
            action_type=str(item["action_type"]),
            parameters=dict(item.get("parameters", {})),
            expected_change=str(item.get("expected_change", "")),
            description=str(item.get("description", "")),
        )
