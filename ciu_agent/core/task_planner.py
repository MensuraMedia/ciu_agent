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
    "You are a GUI task execution planner for a desktop automation agent "
    "called CIU (Complete Interface Usage). The agent controls the mouse "
    "cursor and keyboard to interact with a real desktop.\n"
    "\n"
    "CRITICAL: The agent has TWO execution modes. You MUST use both:\n"
    "\n"
    "1. VISUAL MODE — Use a zone_id from the zone list. The agent will "
    "physically move the mouse cursor to the zone's center and perform "
    "the action (click, type, etc.). The user sees the cursor move.\n"
    "\n"
    '2. COMMAND MODE — Use zone_id "__global__" for keyboard shortcuts '
    "that have no on-screen target (Win+R, Ctrl+S, Enter, etc.).\n"
    "\n"
    "=== MANDATORY RULES ===\n"
    "RULE 1: If a zone exists in the zone list that matches the element "
    "you want to interact with, you MUST use that zone's id. Do NOT use "
    '"__global__" when a matching zone is available.\n'
    "\n"
    "RULE 2: For EVERY click action, use the zone_id of the target "
    "element. The agent needs zone_id to navigate the cursor there.\n"
    "\n"
    "RULE 3: For text input into a visible text field, FIRST click the "
    "text field zone (visual mode), THEN type_text into that same zone "
    'or use "__global__" type_text if the field is now focused.\n'
    "\n"
    'RULE 4: Only use "__global__" for:\n'
    "  - Keyboard shortcuts (Ctrl+S, Alt+F4, Win+R, Enter, Tab, etc.)\n"
    "  - Typing text when the target field is already focused and has "
    "no zone_id\n"
    "  - OS-level actions with no visible UI target\n"
    "\n"
    "RULE 5: After steps that change the screen significantly (opening "
    "an app, opening a dialog), the agent will re-capture the screen "
    "and detect NEW zones. Your plan should include a PLACEHOLDER step "
    'with zone_id "__replan__" and action_type "replan" to signal that '
    "the agent should re-plan the remaining steps with the new zones.\n"
    "\n"
    "=== METHODOLOGY ===\n"
    "1. EXAMINE: Review all zones to understand the current screen.\n"
    "2. IDENTIFY: Determine OS and visible applications from zone labels.\n"
    "3. LOCATE LAUNCHER: Find Start menu / taskbar / dock zones.\n"
    "4. ACCESS LAUNCHER: Click the Start/Search zone (visual mode) or "
    'use "__global__" key_press if no launcher zone exists.\n'
    "5. FIND APP: Type to search, scroll, or click through menus.\n"
    "6. OPEN APP: Click the app entry, then add a replan step.\n"
    "7. OPERATE: Use zone_ids for buttons, menus, text fields.\n"
    "8. COMPLETE: Save, confirm, or close as needed.\n"
    "\n"
    "=== OUTPUT FORMAT ===\n"
    "Return ONLY a JSON array. Each element:\n"
    "{\n"
    '  "step_number": int,\n'
    '  "zone_id": "zone_abc123" or "__global__" or "__replan__",\n'
    '  "zone_label": "human label",\n'
    '  "action_type": "click"|"double_click"|"type_text"|"key_press"'
    '|"scroll"|"replan",\n'
    '  "parameters": {"text": "..."} or {"key": "..."} or {},\n'
    '  "expected_change": "description of screen change",\n'
    '  "description": "what this step does"\n'
    "}\n"
    "\n"
    "=== EXAMPLES ===\n"
    "Example 1 — Clicking a visible Start button:\n"
    '  {"step_number": 1, "zone_id": "zone_start_btn", '
    '"zone_label": "Start", "action_type": "click", '
    '"parameters": {}, "expected_change": "Start menu opens", '
    '"description": "Click the Start button to open the Start menu"}\n'
    "\n"
    "Example 2 — Typing into a visible search box:\n"
    '  {"step_number": 2, "zone_id": "zone_search_box", '
    '"zone_label": "Search box", "action_type": "click", '
    '"parameters": {}, "expected_change": "Search box is focused", '
    '"description": "Click the search box to focus it"}\n'
    '  {"step_number": 3, "zone_id": "__global__", '
    '"zone_label": "keyboard", "action_type": "type_text", '
    '"parameters": {"text": "notepad"}, '
    '"expected_change": "Search results appear", '
    '"description": "Type notepad to search for it"}\n'
    "\n"
    "Example 3 — Keyboard shortcut (no zone needed):\n"
    '  {"step_number": 4, "zone_id": "__global__", '
    '"zone_label": "keyboard", "action_type": "key_press", '
    '"parameters": {"key": "ctrl+s"}, '
    '"expected_change": "Save dialog appears", '
    '"description": "Press Ctrl+S to save"}\n'
    "\n"
    "Example 4 — Replan after launching an app:\n"
    '  {"step_number": 5, "zone_id": "__replan__", '
    '"zone_label": "replan", "action_type": "replan", '
    '"parameters": {}, '
    '"expected_change": "New application zones detected", '
    '"description": "Re-capture screen and plan remaining steps '
    'with new zones"}\n'
    "\n"
    "=== GUIDELINES ===\n"
    "- Keep plans short. Only plan steps up to the next major screen "
    'change, then add a "__replan__" step.\n'
    "- Common keyboard shortcuts:\n"
    '  Windows: {"key": "win"} (Start), {"key": "win+r"} (Run), '
    '{"key": "ctrl+s"} (Save), {"key": "alt+f4"} (Close), '
    '{"key": "enter"} (Confirm)\n'
    '  macOS: {"key": "cmd+space"} (Spotlight), {"key": "cmd+s"} '
    "(Save)\n"
    "- Use real file paths, not environment variables like "
    "%USERPROFILE%. For Windows use C:\\Users\\<username>\\Documents.\n"
    "- IMPORTANT: You will be called MULTIPLE times as the screen "
    "changes. Each call provides fresh zones. Plan only for what you "
    "can see NOW.\n"
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

    def build_prompt(
        self,
        task: str,
        zones: list[Zone],
        completed_steps: list[str] | None = None,
    ) -> dict:
        """Build the Claude Messages API payload for task planning.

        Returns a ``dict`` ready to be serialised to JSON and sent to
        ``/v1/messages``.  The payload is text-only (no images).

        Args:
            task: Natural-language description of the task.
            zones: Currently available UI zones on screen.
            completed_steps: Optional list of step descriptions that
                have already been completed (for adaptive replanning).

        Returns:
            A dictionary matching the Anthropic Messages API schema.
        """
        zone_summary = self._summarize_zones(zones)
        os_line = (
            f"Operating system: {self._platform_name}\n"
            if self._platform_name
            else ""
        )

        progress_text = ""
        if completed_steps:
            progress_text = (
                "\n=== ALREADY COMPLETED (DO NOT REPEAT) ===\n"
                "The following steps have ALREADY been executed "
                "successfully. Do NOT include these in your plan:\n"
                + "\n".join(
                    f"  DONE {i+1}. {desc}"
                    for i, desc in enumerate(completed_steps)
                )
                + "\n\nIMPORTANT: Plan ONLY the remaining steps needed "
                "to finish the task. The application is already open "
                "and ready. Do NOT reopen it.\n"
            )

        clickable_count = sum(
            1 for z in zones
            if z.type.value in (
                "button", "menu", "text_field", "link",
                "icon", "tab", "checkbox", "radio",
            )
        )

        user_text = (
            f"Task: {task}\n"
            "\n"
            f"{os_line}"
            f"Zones detected: {len(zones)} "
            f"({clickable_count} clickable)\n"
            f"{progress_text}"
            "\n"
            "AVAILABLE ZONES (use these zone_ids for visual mode):\n"
            f"{zone_summary}\n"
            "\n"
            "REMINDER: You MUST use zone_id from the list above for "
            "any element you want to click or interact with. Only use "
            '"__global__" for keyboard shortcuts with no visible target.'
            "\n\n"
            "Plan the next steps to accomplish the task."
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

    def plan(
        self,
        task: str,
        zones: list[Zone],
        completed_steps: list[str] | None = None,
    ) -> TaskPlan:
        """Decompose a task into an ordered list of zone interactions.

        This is a synchronous (blocking) method.  It builds the prompt,
        calls the Claude API with retry and exponential back-off, then
        parses the response into ``TaskStep`` objects.

        Args:
            task: Natural-language description of the task to
                accomplish.
            zones: Currently available UI zones on screen.
            completed_steps: Optional list of already-completed step
                descriptions for adaptive replanning.

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

        payload = self.build_prompt(task, zones, completed_steps)
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
