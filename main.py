#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.12"
# dependencies =[
#     "langchain",
#     "langchain-openai",
#     "langchain-community",
#     "langchain-tavily",
#     "tavily-python",
#     "prompt_toolkit",
#     "pydantic",
#     "python-dotenv",
#     "singlestoredb",
# ]
# ///
"""
True Practical AI DevOps Agent (LangChain + Persistent Shell + uv + dotenv)

Maintains a single persistent PTY bash session. The AI agent executes commands
step-by-step, analyzes real-time output, and dynamically handles errors or state
changes (like `cd` or `export`).
"""
# Licensed under the MIT License

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
import re
from typing import Optional, Tuple

# Third-party

# Local modules
import config
from common_types import QuitExecutionException, FinishExecutionException, ExecutionStep
from utils.threads import (
    cleanup_all_threads
)
from utils.terminal import restore_terminal, safe_prompt, init_auto_approve_mode, edit_in_vim, BOLD, CYAN, RESET
from utils.io import read_markdown_file, fetch_url_content, extract_url_title
from utils.os_info import get_detailed_os_info, is_url, is_markdown_file
from shell.persistent import PersistentShell
from cache import create_plan_cache, BasePlanCache
from llm.setup import setup_llm
from agents.planner import PlannerAgent
from agents.executor import ExecutorAgent
from agents.auditor import AuditorAgent

# ══════════════════════════════════════════════════════════════════
# Global state
# ══════════════════════════════════════════════════════════════════

AUTO_APPROVE_MODE: bool = False


# ══════════════════════════════════════════════════════════════════
# Helper functions (formerly in main.py)
# ══════════════════════════════════════════════════════════════════

def _show_plan_diff(original: str, distilled: str) -> None:
    """Print a unified diff between *original* and *distilled* plans."""
    import difflib
    original_lines = original.splitlines(keepends=True)
    distilled_lines = distilled.splitlines(keepends=True)
    
    diff = list(difflib.unified_diff(
        original_lines,
        distilled_lines,
        fromfile="original plan",
        tofile="distilled plan",
        lineterm="",
    ))
    if not diff:
        print("(No differences — distilled plan is identical to original)")
        return
    print("\n" + "=" * 60)
    print("📊 Diff: original → distilled")
    print("=" * 60)
    for line in diff:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            print(line)
        elif line.startswith("+"):
            print(f"\033[32m{line}\033[0m")   # green for additions
        elif line.startswith("-"):
            print(f"\033[31m{line}\033[0m")   # red for removals
        else:
            print(line)
    print("=" * 60)


def _first_non_empty_line(text: str) -> str:
    """Return the first non-empty line from text, or empty string if none."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _format_source_label(plan_entry: dict) -> str:
    if plan_entry.get('url'):
        return f"URL   : {plan_entry['url']}"
    if plan_entry.get('markdown_file'):
        return f"File  : {os.path.basename(plan_entry['markdown_file'])}"
    return "Source: Manual Task"


def _save_distilled_to_cache(
    plan_cache: BasePlanCache,
    planner: PlannerAgent,
    distilled_plan: str,
    original_plan: str,
    original_plan_meta: dict,
) -> None:
    """Overwrite a cached plan entry with the distilled version.

    *original_plan_meta* is a dict from plan_cache.list_plans() for the plan
    being replaced — it carries task_hash, task_text, url, markdown_file etc.
    *original_plan* is the original plan string (used to extract title).
    *distilled_plan* is expected to already have the title prepended by the caller.
    """
    # The distilled_plan already has the title prepended by the caller.
    saved_plan = distilled_plan

    # Extract the first non-empty line from original_plan as the title for metadata
    title = _first_non_empty_line(original_plan)
    
    # Use the extracted title for metadata (with fallback to original task_text)
    # This ensures the title line is preserved in the cache entry's task_text
    if title:
        task_text_to_store = title[:200]
    else:
        task_text_to_store = original_plan_meta.get('task_text', '')
    
    url = original_plan_meta.get("url")
    md  = original_plan_meta.get("markdown_file")
    if url:
        task_for_cache   = url
        embedding_text   = task_text_to_store
        url_to_store     = url
        md_to_store      = None
    elif md:
        task_for_cache   = md
        embedding_text   = task_text_to_store
        url_to_store     = None
        md_to_store      = md
    else:
        # For normal tasks, we don't have the original cache key (user task + distro).
        # But we are overwriting via task_hash, so the exact task argument doesn't matter.
        # Use task_text_to_store for consistency with normal saves.
        task_for_cache   = task_text_to_store
        embedding_text   = task_text_to_store
        url_to_store     = None
        md_to_store      = None

    plan_cache.set(
        task_for_cache,
        saved_plan,
        skip_embedding=False,
        embedding_text=embedding_text,
        url=url_to_store,
        markdown_file=md_to_store,
        task_text=task_text_to_store,
        task_hash=original_plan_meta.get('task_hash'),
    )


def _parse_action_command(user_input: str) -> Tuple[Optional[str], Optional[int]]:
    """Parse commands like 'e1', 'edit 1', 'd1', 'delete 1', 'r1', 'run 1'.
    Returns (action, index) if it's a valid action on an index, else (None, None).
    """
    s = user_input.strip().lower()
    
    # 1. Shorthand like 'e1', 'd1', 'r1'
    m = re.fullmatch(r'([edr])(\d+)', s)
    if m:
        action = {'e': 'edit', 'd': 'delete', 'r': 'run'}[m.group(1)]
        return action, int(m.group(2))
        
    # 2. Space-separated like 'edit 1', 'e 1', 'delete 1', 'd 1', 'run 1', 'r 1'
    parts = s.split()
    if len(parts) == 2 and parts[1].isdigit():
        cmd, idx = parts[0], int(parts[1])
        if cmd in ('edit', 'ed', 'e'):
            return 'edit', idx
        if cmd in ('delete', 'del', 'rm', 'd'):
            return 'delete', idx
        if cmd in ('run', 'r'):
            return 'run', idx
            
    return None, None


def _audit_plan_interactive(plan: str, auditor) -> bool:
    """Audit the plan and display warnings if dangerous commands are found.
    Returns True always (warning is shown but execution continues).
    The actual save/execute decision is made by the user in the main flow.
    """
    if auditor is None:
        return True

    dangerous_commands = auditor.audit_plan(plan)
    if not dangerous_commands:
        print("\n✅ Plan passes security audit.")
        return True

    warning = auditor.format_warnings(dangerous_commands)
    print(warning)
    # No prompt here - just show warning and continue
    return True


def _normalize_plan_for_container(plan: str) -> str:
    """Normalize plan for container/root environments (strip sudo, convert systemctl to service)."""
    import re

    lines = plan.splitlines()
    out: list[str] = []
    expect_command = False
    for raw in lines:
        line = raw
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        if stripped.startswith("```"):
            out.append(line)
            continue
        if re.match(r"^##\s+\d+\.?", stripped):
            expect_command = True
            out.append(line)
            continue
        if expect_command:
            # 1. Remove sudo after optional env prefix
            m = re.match(r"^(\s*(?:[A-Z_][A-Z0-9_]*=[^\\s]+\s+)*)sudo\s+(.*)$", line)
            if m:
                line = f"{m.group(1)}{m.group(2)}"
            
            # 2. Convert systemctl to service
            # Handle start|stop|restart|status|reload
            line = re.sub(
                r"systemctl(?:\s+-[a-zA-Z0-9-]+)?\s+(start|stop|restart|status|reload)\s+([a-zA-Z0-9._-]+)",
                r"service \2 \1",
                line
            )
            # Handle enable|disable (convert to service start as a best-effort fallback in containers)
            line = re.sub(
                r"systemctl(?:\s+-[a-zA-Z0-9-]+)?\s+(enable|disable)\s+([a-zA-Z0-9._-]+)",
                r"service \2 start",
                line
            )
            
            expect_command = False
            out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def _mark_container_in_title(plan: str) -> str:
    """Append a container marker to the title line if not already present."""
    lines = plan.splitlines()
    if not lines:
        return plan
    title = lines[0].strip()
    if title.startswith("# ") and "container" not in title.lower():
        lines[0] = f"{title} (container)"
    return "\n".join(lines)


def main(initial_input: str = None, sandbox_type: str = None) -> None:
    """Main entry point.
    
    Args:
        initial_input: Initial task to execute
        sandbox_type: Execution backend ('host', 'docker', 'podman', 'firecracker')
    """
    init_auto_approve_mode()

    print("=" * 60)
    print("🚀 Practical AI DevOps Agent Initializing...")
    print("=" * 60)

    llm = setup_llm()
    
    # Determine sandbox type (command-line arg takes precedence over env var)
    if sandbox_type is None:
        sandbox_type = config.SANDBOX_TYPE
    
    # Initialize execution backend
    from shell.sandbox import create_backend
    try:
        print(f"🔧 Initializing {sandbox_type} execution backend...")
        backend = create_backend(sandbox_type, image=config.SANDBOX_IMAGE)
        backend.initialize()
    except Exception as e:
        restore_terminal()
        print(f"❌ Failed to initialize {sandbox_type} backend: {e}")
        sys.exit(1)
    
    # Create persistent shell wrapper around the backend
    # or use the backend directly for container modes
    if sandbox_type == 'host':
        persistent_shell = backend.shell
    else:
        # For container backends, create a wrapper
        from shell.shell_wrapper import ShellWrapper
        persistent_shell = ShellWrapper(backend)
    
    # Get OS info: use container's OS if sandbox mode is enabled
    if sandbox_type != 'host':
        try:
            os_info = backend.get_os_info()
            print(f"📦 Target OS: {os_info.split(chr(10))[0][:80]}")
        except Exception as e:
            # Fallback to host OS if container OS info retrieval fails
            print(f"⚠️  Could not get container OS info: {e}")
            print("   Using host OS info as fallback")
            os_info = get_detailed_os_info()
    else:
        os_info = get_detailed_os_info()

    plan_cache = create_plan_cache()
    print(f"💾 Plan cache initialized ({plan_cache.ttl_days}-day TTL)")
    print("\n🧹 Cleaning up expired plan cache entries...")
    deleted = plan_cache.cleanup_expired()
    if deleted > 0:
        print(f"✅ Cleanup complete: {deleted} expired plan(s) removed")
    else:
        print("✅ No expired plan entries found")

    # In container backends we typically run as root; avoid sudo in plans.
    no_sudo = sandbox_type != 'host'

    planner = PlannerAgent(llm=llm, plan_cache=plan_cache, os_info=os_info)
    executor = ExecutorAgent(llm=llm, shell=persistent_shell, os_info=os_info, is_sandbox=no_sudo)
    auditor = AuditorAgent() if config.ENABLE_AUDITOR else None

    print("✅ System Ready. Persistent shell session established.")
    # Determine display modes based on configuration
    planner_mode = "Planner"
    if config.TAVILY_API_KEY:
        planner_mode += " (with Tavily search)"
    else:
        planner_mode += " (no search)"
    
    modes = [planner_mode]
    if config.ENABLE_AUDITOR:
        modes.append("Auditor (enabled)")
    modes.append("Executor (shell)")
    
    print(f"🤖 Agent Modes: {' + '.join(modes)}")

    print("\n" + "=" * 60)
    print("⚠️  IMPORTANT WARNING")
    print("=" * 60)
    print("This tool is designed EXCLUSIVELY for creating disposable test")
    print("environments. It is NOT intended for production use.")
    print("The agent executes AI-generated commands which may DESTROY your")
    print("environment. Use entirely at your own risk.")
    print("=" * 60)

    # ── Session state for plan-refinement feature ─────────────────
    # After a successful execution these are populated so the user can
    # immediately run 'refine' to distil a clean plan from the log.
    _last_execution_log: list[ExecutionStep] = []   # commands run in last execution
    _last_executed_plan: str = ""                    # plan that was executed
    _last_task: str = ""                            # user task string
    _last_plan_meta: Optional[dict] = None          # list_plans() entry for the plan

    try:
        while True:
            try:
                print("\n" + "=" * 60)
                print("📋 Quick Guide:")
                print("  • Enter a task description (e.g., 'Install Nginx')")
                print("  • Enter a URL to fetch content (e.g., 'https://example.com/guide')")
                print("  • Enter a markdown file path (e.g., './setup.md')")
                print("  • 'ls' — list cached plans")
                print("  • 'run N' or 'rN' — run a cached plan directly (e.g., 'run 1', 'r1')")
                print("  • 'refine' — distil last execution into a clean plan")
                print("  • Type 'quit' or 'q' to exit")
                print("=" * 60)

                if initial_input is not None:
                    user_input = initial_input
                    initial_input = None
                else:
                    user_input = safe_prompt(f"\n{BOLD}{CYAN}🤖 Enter your task ('q' to quit):{RESET} ").strip()
                if user_input.lower() in ('quit', 'q'):
                    print("\n👋 Exiting. Closing shell session.")
                    break
                if not user_input.strip():
                    continue

                # Cache management commands
                if user_input.lower() in ('clear', 'clear cache', 'cc'):
                    print("\n" + "=" * 60)
                    print("🗑️  Clear All Cached Plans")
                    print("=" * 60)
                    stats = plan_cache.get_stats()
                    print("Current cache stats:")
                    print(f"  Total plans: {stats['total_plans']}")
                    print(f"  Valid plans: {stats['valid_plans']}")
                    print(f"  Expired plans: {stats['expired_plans']}")
                    confirm = safe_prompt(f"\n⚠️  Delete ALL {stats['total_plans']} plans? This cannot be undone. [y/N]: ").strip().lower()
                    if confirm == 'y':
                        plan_cache.clear()
                        print("✅ Plan cache cleared.")
                        print(f"Stats after clear: {plan_cache.get_stats()}")
                    else:
                        print("Cancelled.")
                    continue

                if user_input.lower() in ('cleanup', 'cleanup cache', 'expired'):
                    print("\n" + "=" * 60)
                    print("🧹 Cleanup Expired Cache Entries")
                    print("=" * 60)
                    stats = plan_cache.get_stats()
                    expired_count = stats['expired_plans']
                    if expired_count == 0:
                        print("✅ No expired plan cache entries to clean")
                        continue
                    print(f"Found {expired_count} expired entries (older than {plan_cache.ttl_days} days)")
                    confirm = safe_prompt(f"Delete {expired_count} expired entries? [y/N]: ").strip().lower()
                    if confirm == 'y':
                        n = plan_cache.cleanup_expired()
                        stats_after = plan_cache.get_stats()
                        print(f"✅ Cleanup complete: {n} expired entries removed")
                        print(f"   Stats — Total: {stats_after['total_plans']}, Valid: {stats_after['valid_plans']}")
                    else:
                        print("Cancelled.")
                    continue

                # ── refine: distil clean plan from last execution log ─────────
                if user_input.lower() in ('refine', 'distill', 'distil'):
                    print("\n" + "=" * 60)
                    print("✨ Plan Refinement — distil clean plan from execution log")
                    print("=" * 60)

                    if not _last_execution_log:
                        print("❌ No execution log available.")
                        print("   Run a task first, then type 'refine' afterwards.")
                        continue

                    n_steps = len(_last_execution_log)
                    n_ok    = sum(1 for s in _last_execution_log if s.succeeded)
                    n_fail  = n_steps - n_ok
                    print("\n📊 Execution log summary:")
                    print(f"   Total commands : {n_steps}")
                    print(f"   Succeeded      : {n_ok}")
                    print(f"   Failed         : {n_fail}")
                    print(f"\n📋 Original plan ({len(_last_executed_plan)} chars):")
                    print("-" * 60)
                    print(_last_executed_plan)
                    print("-" * 60)

                    confirm_refine = safe_prompt(
                        "\n🤖 Generate distilled plan now? [Y/n/q]: "
                    ).strip().lower()
                    if confirm_refine in ('n', 'no'):
                        print("Cancelled.")
                        continue
                    if confirm_refine in ('q', 'quit'):
                        print("↩️  Returning to task prompt.")
                        continue

                    # Call LLM to distil
                    try:
                        distilled = planner.distill_plan(
                            user_task=_last_task,
                            execution_log=_last_execution_log,
                            original_plan=_last_executed_plan,
                        )
                    except (ValueError, TimeoutError) as e:
                        print(f"\n❌ Distillation failed: {e}")
                        continue
                    except Exception as e:
                        print(f"\n❌ Unexpected error during distillation: {e}")
                        continue

                    # Prepend title from original plan
                    title = _first_non_empty_line(_last_executed_plan)
                    if title:
                        distilled = title + "\n\n" + distilled

                    # Show the distilled plan
                    print("\n" + "=" * 60)
                    print("✨ Distilled Plan:")
                    print("=" * 60)
                    print(distilled)
                    print("=" * 60)

                    # Show diff against original
                    _show_plan_diff(_last_executed_plan, distilled)

                    # Ask user if they want to save
                    save_choice = safe_prompt(
                        "\n💾 Save distilled plan to cache? [Y/n/edit/q]: "
                    ).strip().lower()

                    if save_choice in ('e', 'edit'):
                        distilled = edit_in_vim(distilled)
                        if not distilled or not distilled.strip():
                            print("⚠️  Empty plan after editing — not saved.")
                            continue
                        
                        # Security check for edited distilled plan
                        if not _audit_plan_interactive(distilled, auditor):
                            print("❌ Distilled plan NOT saved due to security concerns.")
                            continue

                        print(f"\n✅ Plan edited ({len(distilled)} chars)")
                        # Re-show diff after manual edit
                        _show_plan_diff(_last_executed_plan, distilled)
                        save_choice = safe_prompt(
                            "\n💾 Save this edited distilled plan? [Y/n]: "
                        ).strip().lower()

                    if save_choice in ('n', 'no'):
                        print("⚠️  Distilled plan NOT saved.")
                        continue
                    if save_choice in ('q', 'quit'):
                        print("↩️  Returning to task prompt.")
                        continue

                    # Always overwrite the original cache entry with the distilled plan.
                    # Build minimal metadata from session state when _last_plan_meta is
                    # unavailable (e.g. the original plan was executed without caching).
                    meta = _last_plan_meta or {
                        "task_text": _last_task,
                        "url": None,
                        "markdown_file": None,
                    }
                    _save_distilled_to_cache(plan_cache, planner, distilled, _last_executed_plan, meta)
                    print("\n✅ Distilled plan saved (overwrote original).")
                    print(f"Cache stats: {plan_cache.get_stats()}")
                    # Update session state to reflect the distilled plan
                    _last_executed_plan = distilled
                    _last_plan_meta = None
                    continue

                # List cached plans (with pagination)
                if user_input.lower() in ('list', 'ls'):
                    # Initialize pagination state for new list command
                    _list_offset = 0
                    _list_page_size = 10
                    _has_more = True
                    
                    while _has_more:
                        print("\n" + "=" * 60)
                        print(f"📋 Cached Plans (page {_list_offset // _list_page_size + 1}):")
                        print("=" * 60)
                        plans = plan_cache.list_plans(limit=_list_page_size, offset=_list_offset)
                        if not plans:
                            print("No cached plans found.")
                            _has_more = False
                        else:
                            for p in plans:
                                age = (datetime.now() - p["timestamp"]).days
                                hash_short = p["task_hash"][:8]
                                task_preview = p["task_text"][:50] + ("..." if len(p["task_text"]) > 50 else "")
                                # Adjust index to reflect global position (offset + local index)
                                global_index = _list_offset + p["index"]
                                index_str = f"[{global_index}] "
                                print(f"\n{index_str}{task_preview}")
                                # Build source label
                                source_label = _format_source_label(p)
                                print(f"    Hash: {hash_short}... | Age: {age}d | {source_label}")
                            
                            # Check if there might be more plans
                            if len(plans) < _list_page_size:
                                print(f"\n📄 End of list (total shown: {_list_offset + len(plans)})")
                                _has_more = False
                            else:
                                print(f"\n⏭️  {_list_offset + 1}-{_list_offset + len(plans)}. 'more' next, 'e<N>' edit, 'd<N>' delete, 'r<N>' run, other=exit")
                                try:
                                    choice = safe_prompt("→ ").strip().lower()
                                    if choice in ('more', 'm'):
                                        _list_offset += _list_page_size
                                        continue
                                    # Handle edit/delete shortcuts/explicit commands
                                    action, target_index = _parse_action_command(choice)
                                    if action:
                                        # Helper handled the parsing
                                        
                                        # Calculate global index range for current page (1-based)
                                        display_start = _list_offset + 1
                                        display_end = _list_offset + len(plans)
                                        
                                        if target_index < display_start or target_index > display_end:
                                            print(f"❌ Index {target_index} is not in the current page (showing {display_start}-{display_end}).")
                                            _has_more = False
                                            break
                                        
                                        # Find the plan with matching global index
                                        matching_plan = next((p for p in plans if (_list_offset + p["index"]) == target_index), None)
                                        if not matching_plan:
                                            print(f"❌ Could not find plan at index {target_index}.")
                                            _has_more = False
                                            break
                                        
                                        if action == 'edit':
                                            # Edit the plan
                                            print("\n" + "=" * 60)
                                            print(f"📝 Editing plan at index {target_index}: {matching_plan['task_text'][:80]}...")
                                            print("=" * 60)
                                            
                                            # Get the full plan from cache
                                            cached_plan = plan_cache.get_by_hash(matching_plan['task_hash'])
                                            if not cached_plan:
                                                print("❌ Could not retrieve plan from cache.")
                                                _has_more = False
                                                break
                                            
                                            # Show current plan
                                            print("\n--- Current Plan ---")
                                            print(cached_plan)
                                            print("--- End of Plan ---\n")
                                            
                                            # Open in editor
                                            edited_plan = edit_in_vim(cached_plan)
                                            if not edited_plan or edited_plan.strip() == cached_plan.strip():
                                                print("⚠️  No changes made.")
                                            else:
                                                # Security check for edited plan
                                                if not _audit_plan_interactive(edited_plan, auditor):
                                                    print("❌ Edit cancelled due to security concerns.")
                                                    _has_more = False
                                                    break
                                                
                                                print("\n" + "=" * 60)
                                                print("📄 Edited Plan:")
                                                print("-" * 60)
                                                print(edited_plan)
                                                print("=" * 60)
                                                
                                                # Ask whether to save
                                                save_edited = safe_prompt("\n💾 Save edited plan to cache? [Y/n/q]: ").strip().lower()
                                                if save_edited in ('q', 'quit'):
                                                    print("↩️  Returning to list view.")
                                                    _has_more = False
                                                    break
                                                elif save_edited in ('y', 'yes', ''):
                                                    # Save the edited plan back to cache
                                                    if matching_plan.get('url'):
                                                        task_for_cache = matching_plan['url']
                                                        embedding_text = None
                                                        url_to_store = matching_plan['url']
                                                        markdown_file_to_store = None
                                                    elif matching_plan.get('markdown_file'):
                                                        task_for_cache = matching_plan['markdown_file']
                                                        embedding_text = None
                                                        url_to_store = None
                                                        markdown_file_to_store = matching_plan['markdown_file']
                                                    else:
                                                        distro = planner._detect_os_distribution()
                                                        task_for_cache = f"{matching_plan['task_text']} {distro}".strip()
                                                        embedding_text = task_for_cache
                                                        url_to_store = None
                                                        markdown_file_to_store = None
                                                    
                                                    edited_first_line = edited_plan.strip().split('\n')[0][:200]
                                                    
                                                    plan_cache.set(
                                                        task_for_cache,
                                                        edited_plan,
                                                        skip_embedding=False,
                                                        embedding_text=embedding_text,
                                                        url=url_to_store,
                                                        markdown_file=markdown_file_to_store,
                                                        task_text=edited_first_line,
                                                        task_hash=matching_plan['task_hash'],  # Overwrite existing entry
                                                    )
                                                    print("✅ Edited plan saved to cache.")
                                                    print(f"Cache stats: {plan_cache.get_stats()}")
                                                else:
                                                    print("⚠️  Edited plan NOT saved to cache (original cached plan remains).")
                                        elif action == 'run':
                                            # Run the cached plan directly
                                            print("\n" + "=" * 60)
                                            print(f"🚀 Running cached plan at index {target_index}: {matching_plan['task_text'][:80]}...")
                                            print("=" * 60)
                                            
                                            # Get the full plan from cache
                                            run_plan = plan_cache.get_by_hash(matching_plan['task_hash'])
                                            if not run_plan:
                                                print("❌ Could not retrieve plan from cache.")
                                                _has_more = False
                                                break
                                            
                                            # Show plan
                                            print("\n📄 Plan:")
                                            print("-" * 60)
                                            print(run_plan)
                                            print("=" * 60)
                                            
                                            # Security audit
                                            if not _audit_plan_interactive(run_plan, auditor):
                                                print("❌ Execution cancelled due to security concerns.")
                                                _has_more = False
                                                break
                                            
                                            while True:
                                                # Confirm execution
                                                run_confirm = safe_prompt("\n✅ Execute this plan? [Y/n/edit/q]: ").strip().lower()
                                                if run_confirm in ('q', 'quit'):
                                                    print("↩️  Returning to list view.")
                                                    _has_more = False
                                                    break
                                                if run_confirm in ('n', 'no'):
                                                    print("❌ Execution cancelled.")
                                                    _has_more = False
                                                    break
                                                elif run_confirm in ('e', 'edit'):
                                                    print("\n📝 Opening plan in editor...")
                                                    edited_plan = edit_in_vim(run_plan)
                                                    if edited_plan and edited_plan.strip() != run_plan.strip():
                                                        run_plan = edited_plan
                                                        # Security check for edited plan
                                                        if not _audit_plan_interactive(run_plan, auditor):
                                                            print("❌ Execution cancelled due to security concerns in edited plan.")
                                                            _has_more = False
                                                            break
                                                            
                                                        # Show the edited plan
                                                        print("\n" + "=" * 60)
                                                        print("📄 Edited Plan:")
                                                        print("-" * 60)
                                                        print(run_plan)
                                                        print("=" * 60)
                                                        
                                                        # Ask whether to save
                                                        save_edited = safe_prompt("\n💾 Save edited plan to cache? [Y/n/q]: ").strip().lower()
                                                        if save_edited in ('q', 'quit'):
                                                            print("↩️  Returning to list view.")
                                                            _has_more = False
                                                            break
                                                        elif save_edited in ('y', 'yes', ''):
                                                            # Update cache entry
                                                            if matching_plan.get('url'):
                                                                task_for_cache = matching_plan['url']
                                                            elif matching_plan.get('markdown_file'):
                                                                task_for_cache = matching_plan['markdown_file']
                                                            else:
                                                                distro = planner._detect_os_distribution()
                                                                task_for_cache = f"{matching_plan['task_text']} {distro}".strip()
                                                            
                                                            edited_first_line = run_plan.strip().split('\n')[0][:200]
                                                            
                                                            plan_cache.set(
                                                                task_for_cache,
                                                                run_plan,
                                                                skip_embedding=False,
                                                                embedding_text=matching_plan.get('embedding_text') or task_for_cache,
                                                                url=matching_plan.get('url'),
                                                                markdown_file=matching_plan.get('markdown_file'),
                                                                task_text=edited_first_line,
                                                                task_hash=matching_plan['task_hash'],
                                                            )
                                                            print("✅ Edited plan saved to cache.")
                                                            print(f"Cache stats: {plan_cache.get_stats()}")
                                                        else:
                                                            print("⚠️  Edited plan NOT saved to cache (original cached plan remains).")
                                                        continue
                                                    else:
                                                        print("⚠️  No changes made or empty plan - returning to execution prompt")
                                                        continue
                                                
                                                print("\n🚀 EXECUTING PLAN")
                                                _last_task = matching_plan['task_text']
                                                _last_plan_meta = matching_plan
                                                try:
                                                    result, execution_log = executor.execute_plan_with_log(
                                                        run_plan,
                                                        _last_task,
                                                    )
                                                    _last_execution_log = execution_log
                                                    _last_executed_plan = run_plan
                                                    
                                                    print("\n" + "=" * 60)
                                                    print("🎯 Execution Complete:")
                                                    print("=" * 60)
                                                    print(result)
                                                    print("=" * 60)

                                                    n_ok  = sum(1 for s in execution_log if s.succeeded)
                                                    n_fail = len(execution_log) - n_ok
                                                    if execution_log and n_fail > 0:
                                                        print(f"\n💡 Execution log: {len(execution_log)} commands total "
                                                              f"({n_ok} succeeded, {n_fail} failed).")
                                                        print("   Type 'refine' to distil a clean plan from the successful path.")
                                                        
                                                    # After successful execution, exit list view and return to main prompt
                                                    _has_more = False
                                                    break
                                                except QuitExecutionException:
                                                    print("\n👋 Execution cancelled by user. Returning to task prompt...")
                                                    _has_more = False
                                                    break
                                                except Exception as e:
                                                    print(f"\n❌ Execution error: {e}")
                                                    print("You can retry execution or edit the plan.")
                                                    continue
                                            break
                                        elif action == 'delete':
                                            # Delete the plan
                                            print("\n" + "=" * 60)
                                            print(f"🗑️  Deleting plan at index {target_index}: {matching_plan['task_text'][:80]}...")
                                            print("=" * 60)
                                            
                                            confirm = safe_prompt(f"Delete this plan? [y/N]: ").strip().lower()
                                            if confirm == 'y':
                                                deleted = plan_cache.delete("", index=target_index)
                                                if deleted:
                                                    print("✅ Plan deleted.")
                                                    print(f"Cache stats: {plan_cache.get_stats()}")
                                                else:
                                                    print("❌ Deletion failed.")
                                            else:
                                                print("Cancelled.")
                                        
                                        # After edit/delete/run, exit the list view
                                        _has_more = False
                                        break
                                    else:
                                        _has_more = False
                                except KeyboardInterrupt:
                                    print("\n\n[!] Interrupted. Returning to prompt...")
                                    _has_more = False
                    continue

                # --- Unified Action Logic (Edit/Delete/Run) ---
                action, target_index = _parse_action_command(user_input)
                if action in ('edit', 'delete', 'run') or user_input.lower().startswith(('edit ', 'ed ', 'delete ', 'del ', 'rm ', 'run ', 'r ')):
                    if target_index is not None:
                        index = target_index
                        is_index = True
                        target = str(index)
                    else:
                        parts = user_input.split(maxsplit=1)
                        if len(parts) < 2:
                            print(f"Usage: {parts[0]} <index|task>  (or 'list' to see available plans)")
                            continue
                        target = parts[1].strip()
                        is_index = target.isdigit()
                        index = int(target) if is_index else None
                    
                    if not action:
                        # Fallback for explicit commands without index in shorthand
                        cmd_l = user_input.lower()
                        if cmd_l.startswith(('edit ', 'ed ')):
                            action = 'edit'
                        elif cmd_l.startswith(('delete ', 'del ', 'rm ')):
                            action = 'delete'
                        elif cmd_l.startswith(('run ', 'r ')):
                            action = 'run'
                    
                    # Show preview from cache
                    plans_list = plan_cache.list_plans(limit=100)
                    if is_index:
                        matching = [p for p in plans_list if p.get("index") == index]
                    else:
                        matching = [p for p in plans_list if target.lower() in p["task_text"].lower()]

                    if not matching:
                        if is_index:
                            print("\n" + "=" * 60)
                            print("❌ No matching plans found.")
                            continue
                        # No cache hit and not an index — treat as natural-language task below.
                    else:
                        print("\n" + "=" * 60)

                        if action == 'run':
                            # Directly run a cached plan by index or task text
                            if len(matching) > 1 and not is_index:
                                print(f"Found {len(matching)} matching plans. Please use index to specify:")
                                for p in matching:
                                    print(f"  [{p.get('index', '?')}] {p['task_text'][:60]}...")
                                continue

                            run_plan_meta = matching[0]
                            run_plan = plan_cache.get_by_hash(run_plan_meta['task_hash'])
                            if not run_plan:
                                print("❌ Could not retrieve plan from cache.")
                                continue

                            print("\n" + "=" * 60)
                            print("🚀 Running cached plan:")
                            print("-" * 60)
                            print(f"Task  : {run_plan_meta['task_text'][:80]}")
                            print(_format_source_label(run_plan_meta))
                            print("=" * 60)
                            print("\n📄 Plan:")
                            print("-" * 60)
                            print(run_plan)
                            print("=" * 60)

                            # Security audit
                            if not _audit_plan_interactive(run_plan, auditor):
                                print("❌ Execution cancelled due to security concerns.")
                                continue

                            while True:
                                # Confirm execution
                                run_confirm = safe_prompt("\n✅ Execute this plan? [Y/n/edit/q]: ").strip().lower()
                                if run_confirm in ('q', 'quit'):
                                    print("↩️  Returning to task prompt.")
                                    break
                                if run_confirm in ('n', 'no'):
                                    print("❌ Execution cancelled.")
                                    break
                                elif run_confirm in ('e', 'edit'):
                                    print("\n📝 Opening plan in editor...")
                                    edited_plan = edit_in_vim(run_plan)
                                    if edited_plan and edited_plan.strip() != run_plan.strip():
                                        run_plan = edited_plan
                                        # Security check for edited plan
                                        if not _audit_plan_interactive(run_plan, auditor):
                                            print("❌ Execution cancelled due to security concerns in edited plan.")
                                            break
                                            
                                        # Show the edited plan
                                        print("\n" + "=" * 60)
                                        print("📄 Edited Plan:")
                                        print("-" * 60)
                                        print(run_plan)
                                        print("=" * 60)
                                        
                                        # Ask whether to save
                                        save_edited = safe_prompt("\n💾 Save edited plan to cache? [Y/n/q]: ").strip().lower()
                                        if save_edited in ('q', 'quit'):
                                            print("↩️  Returning to task prompt.")
                                            run_plan = None
                                            break
                                        elif save_edited in ('y', 'yes', ''):
                                            # Update cache entry
                                            if run_plan_meta.get('url'):
                                                task_for_cache = run_plan_meta['url']
                                            elif run_plan_meta.get('markdown_file'):
                                                task_for_cache = run_plan_meta['markdown_file']
                                            else:
                                                distro = planner._detect_os_distribution()
                                                task_for_cache = f"{run_plan_meta['task_text']} {distro}".strip()
                                            
                                            edited_first_line = run_plan.strip().split('\n')[0][:200]
                                            
                                            plan_cache.set(
                                                task_for_cache,
                                                run_plan,
                                                skip_embedding=False,
                                                embedding_text=run_plan_meta.get('embedding_text') or task_for_cache,
                                                url=run_plan_meta.get('url'),
                                                markdown_file=run_plan_meta.get('markdown_file'),
                                                task_text=edited_first_line,
                                                task_hash=run_plan_meta['task_hash'],
                                            )
                                            print("✅ Edited plan saved to cache.")
                                            print(f"Cache stats: {plan_cache.get_stats()}")
                                        else:
                                            print("⚠️  Edited plan NOT saved to cache (original cached plan remains).")
                                        continue
                                    else:
                                        print("⚠️  No changes made or empty plan - returning to execution prompt")
                                        continue

                                # Execute via ExecutorAgent
                                print("\n🚀 EXECUTING PLAN")
                                _last_task = run_plan_meta['task_text']
                                _last_plan_meta = run_plan_meta
                                try:
                                    result, execution_log = executor.execute_plan_with_log(
                                        run_plan,
                                        _last_task,
                                    )
                                    _last_execution_log = execution_log
                                    _last_executed_plan = run_plan

                                    print("\n" + "=" * 60)
                                    print("🎯 Execution Complete:")
                                    print("=" * 60)
                                    print(result)
                                    print("=" * 60)

                                    n_ok  = sum(1 for s in execution_log if s.succeeded)
                                    n_fail = len(execution_log) - n_ok
                                    if execution_log and n_fail > 0:
                                        print(f"\n💡 Execution log: {len(execution_log)} commands total "
                                              f"({n_ok} succeeded, {n_fail} failed).")
                                        print("   Type 'refine' to distil a clean plan from the successful path.")

                                    break
                                except QuitExecutionException:
                                    print("\n👋 Execution cancelled by user. Returning to task prompt...")
                                    break
                                except Exception as e:
                                    print(f"\n❌ Execution error: {e}")
                                    print("You can retry execution or edit the plan.")
                                    continue
                            continue
                        elif action == 'delete':
                            print(f"🗑️  Deleting {len(matching)} matching plan(s):")
                            for p in matching:
                                idx_info = f"[{p.get('index', '?')}] " if 'index' in p else ""
                                print(f"  {idx_info}• {p['task_text'][:60]}... (hash: {p['task_hash'][:12]}...)")

                            confirm = safe_prompt(f"\nDelete {len(matching)} plan(s)? [y/N]: ").strip().lower()
                            if confirm == 'y':
                                if is_index:
                                    deleted = plan_cache.delete("", index=index)
                                else:
                                    deleted = plan_cache.delete(target)
                                if deleted:
                                    print(f"✅ Deleted {len(matching)} plan(s)")
                                else:
                                    print("❌ Deletion failed.")
                            else:
                                print("Cancelled.")
                            continue

                        elif action == 'edit':
                            if len(matching) > 1 and not is_index:
                                print(f"Found {len(matching)} matching plans. Please use index to specify:")
                                for p in matching:
                                    print(f"  [{p.get('index', '?')}] {p['task_text'][:60]}...")
                                continue

                            plan_to_edit = matching[0]
                            print(f"📝 Editing plan: {plan_to_edit['task_text'][:80]}...")
                            print("=" * 60)

                            # Get the full plan from cache using task hash
                            cached_plan = plan_cache.get_by_hash(plan_to_edit['task_hash'])
                            if not cached_plan:
                                print("❌ Could not retrieve plan from cache.")
                                continue

                            # Show current plan
                            print("\n--- Current Plan ---")
                            print(cached_plan)
                            print("--- End of Plan ---\n")

                            # Open in editor
                            edited_plan = edit_in_vim(cached_plan)
                            if not edited_plan or edited_plan.strip() == cached_plan.strip():
                                print("⚠️  No changes made.")
                                continue

                            # Security check for edited plan
                            if not _audit_plan_interactive(edited_plan, auditor):
                                print("❌ Edit cancelled due to security concerns.")
                                continue

                            print("\n" + "=" * 60)
                            print("📄 Edited Plan:")
                            print("-" * 60)
                            print(edited_plan)
                            print("=" * 60)
                            
                            # Ask whether to save
                            save_edited = safe_prompt("\n💾 Save edited plan to cache? [Y/n/q]: ").strip().lower()
                            if save_edited in ('q', 'quit'):
                                print("↩️  Returning to task prompt.")
                                continue
                            elif save_edited in ('y', 'yes', ''):
                                # Save the edited plan back to cache
                                if plan_to_edit.get('url'):
                                    task_for_cache = plan_to_edit['url']
                                    embedding_text = None
                                    url_to_store = plan_to_edit['url']
                                    markdown_file_to_store = None
                                elif plan_to_edit.get('markdown_file'):
                                    task_for_cache = plan_to_edit['markdown_file']
                                    embedding_text = None
                                    url_to_store = None
                                    markdown_file_to_store = plan_to_edit['markdown_file']
                                else:
                                    distro = planner._detect_os_distribution()
                                    task_for_cache = f"{plan_to_edit['task_text']} {distro}".strip()
                                    embedding_text = task_for_cache
                                    url_to_store = None
                                    markdown_file_to_store = None

                                edited_first_line = edited_plan.strip().split('\n')[0][:200]

                                plan_cache.set(
                                    task_for_cache,
                                    edited_plan,
                                    skip_embedding=False,
                                    embedding_text=embedding_text,
                                    url=url_to_store,
                                    markdown_file=markdown_file_to_store,
                                    task_text=edited_first_line,
                                    task_hash=plan_to_edit['task_hash'],  # Overwrite existing entry
                                )
                                print("✅ Edited plan saved to cache.")
                                print(f"Cache stats: {plan_cache.get_stats()}")
                            else:
                                print("⚠️  Edited plan NOT saved to cache (original cached plan remains).")
                new_plan_regenerated = False
                while True:
                    if not new_plan_regenerated:
                        # Use existing user_input from outer prompt; do not re-prompt here.
                        task = user_input.strip()
                        url_content = None
                        markdown_content = None

                        if is_url(task) or is_markdown_file(task):
                            print("\n" + "=" * 60)
                            print("🎯 TWO-PHASE EXECUTION (URL/Markdown Mode)")
                            print("=" * 60)
                            if is_url(task):
                                print("\n🔍 Input detected as URL. Fetching content...")
                                url_content = fetch_url_content(task)
                                url_title = extract_url_title(task)
                                if url_title:
                                    url_content = f"Page Title: {url_title}\n\n{url_content}"
                                print(f"\n📄 URL content fetched ({len(url_content)} characters)")
                            else:
                                print("\n📝 Input detected as markdown file. Reading content...")
                                markdown_content = read_markdown_file(task)
                                print(f"\n📄 Markdown content loaded ({len(markdown_content)} characters)")
                        
                        print("\n" + "=" * 60)
                        print("🎯 TWO-PHASE EXECUTION")
                        print("=" * 60)
                        if planner._tavily_available:
                            print("\n📋 PHASE 1: Planning (with Tavily search)")
                        else:
                            print("\n📋 PHASE 1: Planning (LLM knowledge only - no Tavily search)")

                        # Phase 1: Plan
                        plan_edited = False
                        show_generated_plan = False
                        try:
                            plan, is_from_cache = planner.create_plan(
                                task,
                                url_content=url_content,
                                markdown_content=markdown_content,
                                execution_log=_last_execution_log if _last_execution_log else None
                            )
                            show_generated_plan = bool(plan and not is_from_cache)
                        except Exception as e:
                            print(f"\n❌ Planning failed: {e}")
                            continue
                    else:
                        # coming from regen - plan already generated
                        new_plan_regenerated = False

                    if plan is None:
                        # User cancelled (e.g., entered 'q' at cache selection).
                        # Exit the plan generation loop and return to the task prompt.
                        break

                    # Plan obtained; exit task-input loop to proceed to save/execute.
                    break

                # create_plan returns (None, False) when user cancels (e.g. q at cache menu)
                if plan is None:
                    continue
    
                # Normalize plan for container/root environments
                if no_sudo and plan:
                    plan = _normalize_plan_for_container(plan)
                    plan = _mark_container_in_title(plan)

                # Display the plan once: adjusted label in sandbox mode, plain label in host mode
                if is_from_cache and plan:
                    print("\n" + "=" * 60)
                    if no_sudo:
                        print("📄 Cached Plan (container adjusted):")
                    else:
                        print("📄 Cached Plan:")
                    print("-" * 60)
                    print(plan)
                    print("=" * 60)

                if show_generated_plan and plan:
                    print("\n" + "=" * 60)
                    print("📄 Generated Plan:")
                    print("-" * 60)
                    print(plan)
                    print("=" * 60)

                # If auditor is enabled, audit the plan and show warnings if needed
                # The actual save decision is made in the normal save prompt below
                if auditor is not None:
                    dangerous_commands = auditor.audit_plan(plan)
                    if dangerous_commands:
                        warning = auditor.format_warnings(dangerous_commands)
                        print(warning)
                        # No additional prompt here - proceed to normal save confirmation
                    else:
                        print("\n✅ Plan passes security audit.")
    
                if plan is None:
                    continue   # Skip to next iteration of the main loop
    
                # Precompute cache-independent metadata
                if url_content:
                    task_for_cache = task  # Use original URL for cache key
                    url_to_store = task    # Store original URL in url column (NOT url_content)
                    markdown_file_to_store = None
                elif markdown_content:
                    task_for_cache = task  # Use original file path for cache key
                    url_to_store = None
                    markdown_file_to_store = task  # Store original file path in markdown_file column
                else:
                    task_for_cache = planner._get_task_with_os(task)
                    url_to_store = None
                    markdown_file_to_store = None

                regen_requested = False
                while True:
                    # Ask user if they want to execute (and save) the plan
                    if not is_from_cache or plan_edited:
                        while True:
                            save_confirm = safe_prompt("\n💾 Save this plan to cache? [Y/n/edit/q]: ").strip().lower()
                            if save_confirm in ('q', 'quit'):
                                print("↩️  Returning to task prompt.")
                                plan = None
                                break
                            elif save_confirm in ("y", "yes", ""):
                                # Compute task_text and embedding_text from plan
                                title = _first_non_empty_line(plan)
                                task_text_to_store = title[:200] if title else task[:200]
                                embedding_text = task_text_to_store

                                plan_cache.set(
                                    task_for_cache,
                                    plan,
                                    skip_embedding=False,
                                    embedding_text=embedding_text,
                                    url=url_to_store,
                                    markdown_file=markdown_file_to_store,
                                    task_text=task_text_to_store,
                                )
                                plan_cache.optimize()
                                print(f"\n✅ Plan saved to cache ({len(plan)} chars)")
                                print(f"Cache stats: {plan_cache.get_stats()}")
                                break
                            elif save_confirm in ("edit", "e"):
                                print("\n📝 Opening plan in editor...")
                                edited_plan = edit_in_vim(plan)
                                if edited_plan and edited_plan.strip() != plan.strip():
                                    plan = edited_plan
                                    if no_sudo and plan:
                                        plan = _normalize_plan_for_container(plan)
                                        plan = _mark_container_in_title(plan)
                                    # Show the edited plan
                                    print("\n" + "=" * 60)
                                    print("📄 Edited Plan:")
                                    print("-" * 60)
                                    print(plan)
                                    print("=" * 60)
                                    # Ask whether to save
                                    save_edited = safe_prompt("\n💾 Save edited plan to cache? [Y/n/q]: ").strip().lower()
                                    if save_edited in ('q', 'quit'):
                                        print("↩️  Returning to task prompt.")
                                        plan = None
                                        break
                                    elif save_edited in ('y', 'yes', ''):
                                        title = _first_non_empty_line(plan)
                                        task_text_to_store = title[:200] if title else task[:200]
                                        embedding_text = task_text_to_store
                                        plan_cache.set(
                                            task_for_cache,
                                            plan,
                                            skip_embedding=False,
                                            embedding_text=embedding_text,
                                            url=url_to_store,
                                            markdown_file=markdown_file_to_store,
                                            task_text=task_text_to_store,
                                        )
                                        plan_cache.optimize()
                                        print(f"✅ Edited plan saved to cache ({len(plan)} chars)")
                                        print(f"Cache stats: {plan_cache.get_stats()}")
                                    else:
                                        print("⚠️  Edited plan NOT saved to cache.")
                                    # Security check for edited plan
                                    if not _audit_plan_interactive(plan, auditor):
                                        print("❌ Execution cancelled due to security concerns in edited plan.")
                                        plan = None
                                        break
                                    plan_edited = True
                                    break
                                else:
                                    print("\n⚠️  No changes made or empty plan - not saved")
                            else:
                                print(f"\n✅ Plan created but NOT cached ({len(plan)} chars)")
                                break

                    # If plan was cancelled during save confirmation, return to task prompt
                    if plan is None:
                        break

                    while True:
                        confirm = safe_prompt("\n✅ Execute this plan? [Y/n/edit/q/regen]: ").strip().lower()
                        if confirm in ('q', 'quit'):
                            print("↩️  Returning to task prompt.")
                            break
                        elif confirm in ('n', 'no'):
                            print("❌ Execution cancelled by user.")
                            # If this plan came from cache, offer to generate a new one
                            if is_from_cache:
                                regen = safe_prompt("Generate a new plan instead? [y/N]: ").strip().lower()
                                if regen in ('y', 'yes'):
                                    print("\n🔄 Generating a new plan (skipping cache)...")
                                    try:
                                        plan, is_from_cache = planner.create_plan(
                                            task,
                                            url_content=url_content,
                                            markdown_content=markdown_content,
                                            execution_log=_last_execution_log if _last_execution_log else None,
                                            skip_cache=True,
                                        )
                                        if plan:
                                            if no_sudo:
                                                plan = _normalize_plan_for_container(plan)
                                                plan = _mark_container_in_title(plan)
                                            print("\n📄 New Plan:")
                                            print("-" * 60)
                                            print(plan)
                                            print("=" * 60)
                                            new_plan_regenerated = True
                                            plan_edited = False
                                            regen_requested = True
                                            break  # Break execution loop to hit Save prompt
                                        else:
                                            plan = None
                                            break
                                    except Exception as e:
                                        print(f"\n❌ Failed to generate new plan: {e}")
                                        plan = None
                                        break
                                else:
                                    plan = None
                                    break
                            else:
                                plan = None
                                break
                        elif confirm in ('regen', 'r'):
                            # Explicit regeneration request
                            print("\n🔄 Generating a new plan (skipping cache)...")
                            try:
                                plan, is_from_cache = planner.create_plan(
                                    task,
                                    url_content=url_content,
                                    markdown_content=markdown_content,
                                    execution_log=_last_execution_log if _last_execution_log else None,
                                    skip_cache=True,
                                )
                                if plan:
                                    if no_sudo:
                                        plan = _normalize_plan_for_container(plan)
                                        plan = _mark_container_in_title(plan)
                                    new_plan_regenerated = True
                                    plan_edited = False
                                    regen_requested = True
                                    print("\n📄 New Plan:")
                                    print("-" * 60)
                                    print(plan)
                                    print("=" * 60)
                                    break  # Break execution loop to hit Save prompt
                                else:
                                    print("↩️  Returning to plan review.")
                                    continue
                            except Exception as e:
                                print(f"\n❌ Failed to generate new plan: {e}")
                                print("↩️  Returning to plan review.")
                                continue
                        elif confirm in ('e', 'edit'):
                            print("\n📝 Opening plan in editor...")
                            edited_plan = edit_in_vim(plan)
                            if edited_plan and edited_plan.strip() != plan.strip():
                                print(f"\n✅ Plan edited ({len(edited_plan)} chars)")
                                plan = edited_plan
                                if no_sudo and plan:
                                    plan = _normalize_plan_for_container(plan)
                                    plan = _mark_container_in_title(plan)
                                
                                # Security check for edited plan BEFORE saving
                                print("\n🔍 Running security audit on edited plan...")
                                if not _audit_plan_interactive(plan, auditor):
                                    print("❌ Execution cancelled due to security concerns in edited plan.")
                                    plan = None
                                    break
                                
                                # Ask if user wants to save the edited plan to cache
                                save_edited = safe_prompt("\n💾 Save edited plan to cache? [Y/n/q]: ").strip().lower()
                                if save_edited in ('q', 'quit'):
                                    print("↩️  Returning to task prompt.")
                                    plan = None
                                    break
                                elif save_edited in ('y', 'yes', ''):
                                    # Determine cache key based on input type
                                    if not url_content and not markdown_content:
                                        distro = planner._detect_os_distribution()
                                        task_for_cache = f"{task} {distro}".strip()
                                    else:
                                        task_for_cache = task
                                    # For edited plan, determine task_text and embedding_text
                                    # Use URL title if available, otherwise fall back to first line
                                    if url_content:
                                        # Use first line of the generated plan for embedding
                                        task_text_to_store = plan.strip().split('\n')[0][:200] if plan else task
                                        embedding_text = task_text_to_store
                                        url_to_store = task
                                        markdown_file_to_store = None
                                    elif markdown_content:
                                        # For markdown, use first line of edited plan
                                        task_text_to_store = plan.strip().split('\n')[0][:200] if plan else task
                                        embedding_text = task_text_to_store
                                        url_to_store = None
                                        markdown_file_to_store = task
                                    else:
                                        # Normal task mode
                                        distro = planner._detect_os_distribution()
                                        task_text_to_store = f"{task} {distro}".strip()
                                        embedding_text = task_text_to_store
                                        url_to_store = None
                                        markdown_file_to_store = None
                                    # Save to cache
                                    plan_cache.set(
                                        task_for_cache,
                                        plan,
                                        skip_embedding=False,
                                        embedding_text=embedding_text,
                                        url=url_to_store,
                                        markdown_file=markdown_file_to_store,
                                        task_text=task_text_to_store,
                                    )
                                    print(f"✅ Edited plan saved to cache ({len(plan)} chars)")
                                    print(f"Cache stats: {plan_cache.get_stats()}")
                                else:
                                    print("⚠️  Edited plan NOT saved to cache (original cached plan remains)")
                                    # Even if not saved, we already audited above, so continue to execution
                            else:
                                print("⚠️  No changes made or empty plan - not saved")
                                continue
                            print("\n📄 Current Plan:")
                            print("-" * 60)
                            print(plan)
                            print("-" * 60)
                            print("✅ Plan ready. Review and choose to execute or cancel.")
                            continue
                        else:  # 'y', 'yes', or empty (Enter key)
                            # Phase 2: Execute (with log capture for 'refine' feature)
                            print("\n🚀 PHASE 2: Execution")
                            try:
                                output, exec_log = executor.execute_plan_with_log(plan, task)
                            except QuitExecutionException:
                                print("\n👋 Execution cancelled by user. Returning to task prompt...")
                                break
                            except Exception as e:
                                print(f"\n❌ Execution error: {e}")
                                print("You can retry execution or edit the plan.")
                                continue

                            print("\n" + "=" * 60)
                            print("🎯 Execution Complete:")
                            print("=" * 60)
                            print(output)
                            print("=" * 60)

                            # Store session state so 'refine' can use it immediately
                            _last_execution_log = exec_log
                            _last_executed_plan = plan
                            _last_task = task
                            # If a cached plan was used (exact hit or hybrid selection),
                            # last_cache_meta holds its original metadata so 'refine'
                            # overwrites the correct entry via the stored task_hash.
                            if planner.last_cache_meta is not None:
                                _last_plan_meta = planner.last_cache_meta
                                planner.last_cache_meta = None
                            else:
                                # New plan was generated — find its metadata by hash
                                try:
                                    all_plans = plan_cache.list_plans(limit=100)
                                    distro = planner._detect_os_distribution()
                                    task_key = f"{task} {distro}".strip().lower()
                                    _last_plan_meta = next(
                                        (p for p in all_plans
                                         if p["task_text"].lower() == task_key
                                         or p.get("url") == task
                                         or p.get("markdown_file") == task),
                                        None,
                                    )
                                except Exception:
                                    _last_plan_meta = None

                            n_ok  = sum(1 for s in exec_log if s.succeeded)
                            n_fail = len(exec_log) - n_ok
                            if exec_log and n_fail > 0:
                                print(f"\n💡 Execution log: {len(exec_log)} commands total "
                                      f"({n_ok} succeeded, {n_fail} failed).")
                                print("   Type 'refine' to distil a clean plan from the successful path.")
                            break

                    if regen_requested:
                        regen_requested = False
                        continue
                    break

                # If cancelled or after execution complete, continue to next task prompt
                if plan is None:
                    continue
                if confirm in ('n', 'no'):
                    continue
                # After execution (success or failure), also continue to next prompt
                continue

            except KeyboardInterrupt:
                restore_terminal()
                print("\n\n[!] Interrupted by user. Returning to task prompt...")
                continue

    finally:
        restore_terminal()
        persistent_shell.close()
        cleanup_all_threads()


# ══════════════════════════════════════════════════════════════════
# CLI Entry point
# ══════════════════════════════════════════════════════════════════

def cli_main() -> None:
    """CLI entry point for planner-shell command."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Practical AI DevOps Agent with containerized execution support"
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="Task description, URL, or markdown file path"
    )
    parser.add_argument(
        "--sandbox",
        choices=["host", "docker", "podman", "firecracker"],
        default=None,
        help="Execution backend (default: host). Use docker/podman for isolated execution."
    )
    parser.add_argument(
        "--image",
        default=None,
        help="Container image to use (for docker/podman backends)"
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve commands without human review"
    )
    
    args = parser.parse_args()
    
    try:
        restore_terminal()
        
        # Set environment for auto-approve if requested
        if args.auto_approve:
            os.environ['AUTO_APPROVE'] = '1'
        
        # Override config image if provided via CLI
        if args.image:
            config.SANDBOX_IMAGE = args.image
        
        main(initial_input=args.task, sandbox_type=args.sandbox)
    except KeyboardInterrupt:
        restore_terminal()
        print("\n👋 Exiting...")
    finally:
        restore_terminal()


if __name__ == "__main__":
    cli_main()
