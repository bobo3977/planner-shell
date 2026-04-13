#!/usr/bin/env python3
"""
Planner agent: creates execution plans using Tavily search and LLM.
"""

from __future__ import annotations
from langchain_core.messages import SystemMessage, HumanMessage

import os
import subprocess
from datetime import datetime
from typing import Optional

import config
from config import load_prompt
from pydantic import Field

from common_types import ExecutionStep
from utils.security import _check_injection, _wrap_external_content
from utils.threads import _run_agent_in_thread
from utils.terminal import safe_prompt
from llm.setup import _make_agent_with_history, extract_agent_output
from cache.base import BasePlanCache
from utils.spinner import spinning
from agents.prompts.default import (
    URL_CONTENT_SECTION_TEMPLATE,
    MARKDOWN_CONTENT_SECTION_TEMPLATE,
    SEARCH_INFO_SECTION_TEMPLATE,
    SEARCH_GUIDELINES_SECTION_TEMPLATE,
    NO_SEARCH_NOTE_SECTION_TEMPLATE,
    EXECUTION_HISTORY_SECTION_TEMPLATE,
    DISTILL_SYSTEM_PROMPT,
)

try:
    from langchain_tavily import TavilySearch
except ImportError:
    # Fallback for older langchain-community based installations
    from langchain_community.tools.tavily_search import TavilySearchResults as TavilySearch


class TavilySearchWithIndicator(TavilySearch):
    """TavilySearch with a visual indicator and a per-execution search cap."""

    # Counts searches since the last successful shell command.
    # Reset by PersistentShellTool whenever a command succeeds.
    search_count: int = Field(default=0, exclude=True)
    MAX_SEARCHES_PER_COMMAND: int = Field(default=config.MAX_SEARCHES_PER_COMMAND, exclude=True)

    def reset_search_count(self) -> None:
        self.search_count = 0

    def _run(self, query: str, **kwargs) -> str:
        self.search_count += 1
        if self.search_count > self.MAX_SEARCHES_PER_COMMAND:
            msg = (
                f"⛔ Tavily search limit reached "
                f"({self.MAX_SEARCHES_PER_COMMAND} searches since last successful command). "
                "Stop searching and either accept the current state or report failure."
            )
            print(f"\n{msg}")
            return msg

        print("\n" + "=" * 60)
        print("🔍 Tavily Search:")
        print("-" * 60)
        print(f"Query: {query}")
        print(f"(search {self.search_count}/{self.MAX_SEARCHES_PER_COMMAND} since last success)")
        print("=" * 60)
        print("⏳ Searching... (this may take a few seconds)")
        result = super()._run(query, **kwargs)
        if isinstance(result, dict):
            result = __import__('json').dumps(result, ensure_ascii=False)
        print("✅ Search completed")
        return result


class PlannerAgent:
    """Creates execution plans using Tavily search."""

    def __init__(self, llm, plan_cache: BasePlanCache, os_info: str,
                 allow_llm_query_generation: bool = False):
        self.llm = llm
        self.plan_cache = plan_cache
        self.os_info = os_info
        self.allow_llm_query_generation = allow_llm_query_generation
        # Tracks metadata of the last cache entry that was used (exact hit or hybrid
        # selection). Used by main() to build _last_plan_meta for 'refine' so the
        # distilled plan overwrites the correct cache entry.
        # Dict keys: task_hash, task_text, url, markdown_file
        self.last_cache_meta: Optional[dict] = None
        # Initialize Tavily only if API key is available
        tavily_key = os.getenv("TAVILY_API_KEY")
        if tavily_key:
            self._tavily = TavilySearchWithIndicator(max_results=3)
            self._tavily_available = True
        else:
            self._tavily = None
            self._tavily_available = False

    def _detect_os_distribution(self) -> str:
        info = self.os_info.lower()
        # Check for various Linux distributions (includes container images)
        for name, key in (
            ("Alpine", "alpine"),
            ("Ubuntu", "ubuntu"),
            ("Debian", "debian"),
            ("CentOS", "centos"),
            ("RHEL", "rhel"),
            ("Fedora", "fedora"),
            ("BusyBox", "busybox"),
            ("OpenSUSE", "opensuse"),
            ("Arch", "arch"),
        ):
            if key in info:
                return name
        try:
            result = subprocess.run(
                "grep '^ID=' /etc/os-release | head -1",
                shell=True, capture_output=True, text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip().split('=')[1].strip('"').capitalize()
        except (OSError, IndexError, subprocess.SubprocessError):
            pass
        return "Ubuntu"

    def _get_task_with_os(self, task: str) -> str:
        distro = self._detect_os_distribution()
        if distro.lower() not in task.lower():
            return f"{task} {distro}".strip()
        return task.strip()

    def _generate_search_query(self, task: str) -> str:
        return self._get_task_with_os(task)

    def _build_system_prompt(
        self,
        task: str,
        search_query: Optional[str] = None,
        search_results: Optional[str] = None,
        url_content: Optional[str] = None,
        markdown_content: Optional[str] = None,
        execution_log: Optional[list] = None,
    ) -> str:
        """Build the system prompt."""
        current_date = datetime.now().strftime("%Y-%m-%d")

        # Load base prompt
        base_prompt = load_prompt(
            "planner",
            required_vars=["{task}", "{current_date}", "{os_info}"]
        )

        # Build sections
        url_content_section = ""
        markdown_content_section = ""
        search_info_section = ""
        search_guidelines_section = ""
        no_search_note_section = ""
        execution_history_section = ""

        if url_content:
            _check_injection(url_content, "URL content")
            wrapped = _wrap_external_content(url_content, "url")
            url_content_section = URL_CONTENT_SECTION_TEMPLATE.format(url_content=wrapped)
        elif markdown_content:
            _check_injection(markdown_content, "Markdown file")
            wrapped = _wrap_external_content(markdown_content, "markdown")
            markdown_content_section = MARKDOWN_CONTENT_SECTION_TEMPLATE.format(markdown_content=wrapped)
        elif search_query and search_results:
            search_info_section = SEARCH_INFO_SECTION_TEMPLATE.format(
                search_query=search_query,
                search_results=search_results
            )
        elif self.allow_llm_query_generation:
            search_guidelines_section = SEARCH_GUIDELINES_SECTION_TEMPLATE.format()
        else:
            no_search_note_section = NO_SEARCH_NOTE_SECTION_TEMPLATE.format()

        # Build execution history section
        if execution_log:
            successful_commands = []
            for step in execution_log:
                if step.succeeded:
                    successful_commands.append(step.command)
            
            if successful_commands:
                commands_list = "\n".join(
                    f"{i}. {cmd if len(cmd) <= 100 else cmd[:97] + '...'}"
                    for i, cmd in enumerate(successful_commands, 1)
                )
                execution_history_section = EXECUTION_HISTORY_SECTION_TEMPLATE.format(
                    successful_commands_list=commands_list
                )

        # Format the prompt
        prompt = base_prompt.format(
            task=task,
            current_date=current_date,
            os_info=self.os_info,
            url_content_section=url_content_section,
            markdown_content_section=markdown_content_section,
            search_info_section=search_info_section,
            search_guidelines_section=search_guidelines_section,
            no_search_note_section=no_search_note_section,
            execution_history_section=execution_history_section,
        )

        return prompt

    def create_plan(
        self,
        task: str,
        timeout: int = None,
        url_content: Optional[str] = None,
        markdown_content: Optional[str] = None,
        execution_log: Optional[list] = None,
        skip_cache: bool = False,
    ) -> tuple[str, bool]:
        """Return a tuple of (plan, is_from_cache).
        Lookup order:
        ────────────
        1. Exact hash match  → silent instant return (True) [skipped if skip_cache=True].
        2. Hybrid search     → show scored candidates, let user pick one (True) or skip [skipped if skip_cache=True].
        3. Generate new plan → call LLM, return (False).
        
        Args:
            skip_cache: If True, bypass all cache lookups and generate a new plan directly.
        """
        if markdown_content:
            lookup_key = task  # Use file path as cache key
        elif url_content:
            lookup_key = task  # Use URL as cache key
        else:
            lookup_key = self._get_task_with_os(task)

        # ── Skip cache if requested ────────────────────────────────────
        if skip_cache:
            print("\n⏭️  Skipping cache — generating a new plan.")
            candidates = []
        else:
            # ── 1. Exact-hash lookup ──────────────────────────────────
            cached = self.plan_cache.get(lookup_key) if self.plan_cache else None
            if cached:
                print("\n" + "=" * 60)
                print("📋 Plan Cache HIT! (exact match)")
                print("-" * 60)
                print(f"Task: {task[:80]}")
                print(f"Cache stats: {self.plan_cache.get_stats()}")
                self.last_cache_meta = self.plan_cache.get_meta(lookup_key)
                return cached, True

            # ── 2. Hybrid search — skip for URL/markdown, only hash-based ─────────
            # For URL and markdown content, use only exact hash lookup (no hybrid search)
            # because the content is highly specific and hybrid search is unnecessary
            if not self.plan_cache:
                print("\n⚠️  No plan cache available - skipping lookup")
                candidates = []
            elif url_content or markdown_content:
                print("\n⚠️  Skipping hybrid search for URL/markdown input")
                print("   (using exact hash match only)")
                candidates = []
            else:
                # Normal flow: perform hybrid search for regular tasks
                print("\n⚡ Searching cache for similar plans...")
                candidates = self.plan_cache.hybrid_search(lookup_key)

            if candidates:
                print("\n" + "=" * 60)
                print("🔍 Similar cached plans found (hybrid FTS + vector search)")
                print("=" * 60)
                for i, c in enumerate(candidates, 1):
                    age_days = (datetime.now() - c.timestamp).days
                    print(f"\n[{i}] Score: {c.score:.4f}  "
                          f"(FTS: {c.fts_score:.4f} | Vector: {c.vec_score:.4f})  "
                          f"— {age_days}d ago")
                    print(f"     Task : {c.task_text[:100]}")
                    if c.url:
                        print(f"     URL  : {c.url}")
                    if c.markdown_file:
                        import os as _os
                        print(f"     File : {_os.path.basename(c.markdown_file)}")
                    # Show lines 2-4 of the plan as a preview (skip line 1 which matches task_text)
                    all_lines = [line for line in c.plan.splitlines() if line.strip()]
                    preview_lines = all_lines[1:4] if len(all_lines) > 1 else all_lines
                    for line in preview_lines:
                        print(f"     Plan » {line[:90]}")
                print(f"\n[n] Generate a new plan instead")
                print("=" * 60)

                while True:
                    # Skip interactive prompt if running in test mode
                    if os.getenv("PLANNER_SHELL_TEST"):
                        print("⏭️  Skipping cache selection menu (PLANNER_SHELL_TEST=1) — generating a new plan.")
                        break

                    try:
                        raw = safe_prompt(
                            f"\nUse a cached plan? [1-{len(candidates)} / n for new / q to cancel]: "
                        ).strip()
                    except KeyboardInterrupt:
                        from utils.terminal import restore_terminal
                        restore_terminal()
                        raw = ""

                    if raw.lower() in ('q', 'quit'):
                        print("↩️  Returning to task prompt.")
                        return None, False
                    if raw == "" or raw.lower() in ('n', 'new') or raw == str(len(candidates) + 1):
                        print("⏭️  Skipping cache — generating a new plan.")
                        break
                    if raw.isdigit():
                        idx = int(raw) - 1
                        if 0 <= idx < len(candidates):
                            chosen = candidates[idx]
                            print("\n" + "=" * 60)
                            print("📋 Using cached plan:")
                            print("-" * 60)
                            print(f"Task  : {chosen.task_text}")
                            if chosen.url:
                                print(f"URL   : {chosen.url}")
                            if chosen.markdown_file:
                                import os as _os
                                print(f"File  : {_os.path.basename(chosen.markdown_file)}")
                            print(f"Score : {chosen.score:.4f}  "
                                  f"(FTS {chosen.fts_score:.4f} | "
                                  f"Vector {chosen.vec_score:.4f})")
                            self.last_cache_meta = {
                                "task_hash":     chosen.task_hash,
                                "task_text":     chosen.task_text,
                                "url":           chosen.url,
                                "markdown_file": chosen.markdown_file,
                            }
                            return chosen.plan, True
                    print(f"Please enter 1-{len(candidates)}, n (new), or q (cancel).")

        # ── 3. Generate a new plan via LLM ─────────────────────────
        print("\n" + "=" * 60)
        print("📋 Planner: Creating new execution plan...")
        print("-" * 60)
        print(f"Task: {task}")
        print(f"Timeout: {timeout}s")
        print("=" * 60)

        if url_content or markdown_content:
            print("\n✅ Using provided content (skipping Tavily search)")
            search_query = search_results = None
        else:
            if self._tavily_available:
                search_query = self._generate_search_query(task)
                print(f"\n🔍 Generated search query: {search_query}")
                print("\n⏳ Performing initial search...")
                search_results = self._tavily._run(search_query)
            else:
                print("\n⚠️  Tavily API key not available - skipping web search")
                print("   Planning will rely on LLM's internal knowledge only.")
                search_query = search_results = None

        system_prompt = self._build_system_prompt(
            task, search_query=search_query, search_results=search_results,
            url_content=url_content, markdown_content=markdown_content,
            execution_log=execution_log,
        )
        # Force empty tools for planning because search is already performed
        # and result is in the system prompt. This ensures we use the direct LLM bypass
        # which is more reliable for local models.
        tools = []
        # Use a graph-based agent if tools are available
        executable = _make_agent_with_history(self.llm, tools, system_prompt)
        input_data = {"input": task}

        print("\n⏳ Generating plan (may take a while)...")

        timeout_value = config.PLAN_TIMEOUT if timeout is None else timeout
        with spinning("Generating plan..."):
            result = _run_agent_in_thread(
                executable,
                input_dict=input_data,
                session_id="planner_session",
                shell=_NullShell(),
                timeout=float(timeout_value),
            )

        plan = extract_agent_output(result) if result is not None else ""

        # Ensure plan starts with a level 1 header (# Title) for the cache system.
        # Local models sometimes skip the title OR start directly with '## 1.'.
        if plan and not (plan.strip().startswith("# ") or plan.strip().startswith("#\n")):
            import re
            # Try to get a clean OS name like "Alpine Linux" or "Ubuntu 22.04"
            os_name = ""
            pretty_match = re.search(r'PRETTY_NAME="([^"]+)"', self.os_info)
            if pretty_match:
                os_name = pretty_match.group(1)
            else:
                # Fallback to the first word of uname or first line
                os_name = self.os_info.splitlines()[0].split()[0] if self.os_info.strip() else "Linux"
            
            title = f"# {task} on {os_name}"
            plan = f"{title}\n\n{plan}"

        if not plan or len(plan.strip()) < 10:
            raise ValueError(f"Generated plan is too short or empty: {plan[:100]}")

        error_patterns = [
            "I apologize", "I don't see a specific task",
            "Please provide the specific task", "What task would you like me",
        ]
        if any(p in plan for p in error_patterns):
            raise ValueError(f"Planner did not understand the task. Plan: {plan[:200]}")

        # Always create embedding from the task title/subject, even for URL/markdown inputs
        # For URL/markdown inputs, use the first line of the generated plan as embedding text
        # and also as task_text
        embedding_text = None
        url_to_store = None
        markdown_file_to_store = None
        task_text_to_store = None
        if url_content or markdown_content:
            if url_content:
                # For URL, always use first line of the generated plan as title
                plan_first_line = plan.strip().split('\n')[0].lstrip('# ')[:200] if plan else None
                embedding_text = plan_first_line
                task_text_to_store = plan_first_line
                url_to_store = task  # task contains the original URL
            else:
                # For markdown, use first line of the generated plan
                plan_first_line = plan.strip().split('\n')[0].lstrip('# ')[:200] if plan else None
                embedding_text = plan_first_line
                task_text_to_store = plan_first_line
                markdown_file_to_store = task  # task contains the original file path
        else:
            # For normal task input, use first line of plan for both task_text and embedding
            plan_first_line = plan.strip().split('\n')[0].lstrip('# ')[:200] if plan else task.lstrip('# ')
            task_text_to_store = plan_first_line
            embedding_text = plan_first_line

        # Update last_cache_meta for the newly generated plan so that 'refine' knows
        # which entry to overwrite if requested immediately after creation.
        if self.plan_cache:
            # The hash must match the cache key (lookup_key) that will be used when
            # saving the plan. This ensures that refine can locate and overwrite the
            # correct entry.
            self.last_cache_meta = {
                "task_hash":     self.plan_cache._hash_task(lookup_key),
                "task_text":     task_text_to_store,
                "url":           url_to_store,
                "markdown_file": markdown_file_to_store,
            }
        else:
            self.last_cache_meta = None

        # Show plan before save prompt
        return plan, False

    def distill_plan(
        self,
        user_task: str,
        execution_log: list[ExecutionStep],
        original_plan: str,
        timeout: int = None,
    ) -> str:
        """Generate a clean, idempotent plan from a messy execution log.

        Sends the full execution history (commands + exit codes) to the LLM
        and asks it to:
          1. Discard every command that failed and was later superseded.
          2. Keep only the final successful command for each goal (de-duplicate
             retries).
          3. Re-order and annotate the survivors into a clean numbered plan.

        Returns the distilled plan text (does NOT save to cache — the caller
        decides whether to overwrite).
        """
        if not execution_log:
            raise ValueError("Execution log is empty — nothing to distill.")

        # Build a compact transcript: command + exit-code only.
        # The output text is not needed to decide which commands to keep or drop —
        # success/failure is fully captured by the exit code.
        lines = []
        for i, step in enumerate(execution_log, 1):
            status = "exit 0 (SUCCESS)" if step.succeeded else f"exit {step.exit_code} (FAILED)"
            lines.append(f"{i}. [{status}] {step.command}")
        transcript = "\n".join(lines)

        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Load distill prompt from external file or default
        system_prompt = load_prompt(
            "distill",
            required_vars=["{current_date}", "{os_info}", "{user_task}", "{execution_history}"]
        )
        
        # Format the prompt with dynamic variables
        system_prompt = system_prompt.format(
            current_date=current_date,
            os_info=self.os_info,
            user_task=user_task,
            execution_history=transcript
        )

        print("\n⏳ Distilling clean plan from execution log...")
        agent_with_history = _make_agent_with_history(
            self.llm, [], system_prompt  # no tools — pure reasoning task
        )
        timeout_value = config.PLAN_TIMEOUT if timeout is None else timeout
        with spinning("Distilling plan..."):
            result = _run_agent_in_thread(
                agent_with_history,
                input_dict={"input": "Produce the distilled plan now."},
                session_id="distill_session",
                shell=_NullShell(),
                timeout=float(timeout_value),
            )
        distilled = extract_agent_output(result) if result is not None else ""
        if not distilled or len(distilled.strip()) < 10:
            raise ValueError("Distillation returned an empty or too-short plan.")
        return distilled


class _NullShell:
    """Placeholder shell passed to _run_agent_in_thread for the planner,
    which does not execute shell commands and never needs PTY forwarding."""
    master_fd: int = -1
