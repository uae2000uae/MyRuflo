"""MyRuflo CLI — `myruflo run "<task>"`, memory inspection, setup, doctor."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from myruflo.config import load_config
from myruflo.hooks.manager import HooksManager
from myruflo.llm.client import LLMClient
from myruflo.memory.store import MemoryStore
from myruflo.swarm.orchestrator import Orchestrator


def cmd_run(args: argparse.Namespace) -> None:
    config = load_config()
    memory = MemoryStore(config.memory_db_path)
    hooks = HooksManager(config.hooks_log_path, memory)

    try:
        llm = LLMClient(config.api_key)
    except ValueError as exc:
        print(f"ERROR: {exc}\nRun 'myruflo doctor' to check your setup.")
        sys.exit(1)

    force_swarm = True if args.swarm else False if args.no_swarm else None
    orchestrator = Orchestrator(config, llm, memory, hooks)
    report = orchestrator.run(args.task, force_swarm=force_swarm)

    print(f"\nPipeline: {' -> '.join(report.pipeline)}\n")
    for result in report.results:
        print(f"=== {result.role} ({result.turns_used} turn(s)) ===")
        print(result.final_text)
        print()

    memory.close()


def cmd_memory_search(args: argparse.Namespace) -> None:
    config = load_config()
    memory = MemoryStore(config.memory_db_path)
    hits = memory.search(args.namespace, args.query, args.top_k)
    if not hits:
        print("(no matches)")
    for score, text in hits:
        print(f"[{score:.3f}] {text}")
    memory.close()


def cmd_memory_list(args: argparse.Namespace) -> None:
    config = load_config()
    memory = MemoryStore(config.memory_db_path)
    namespaces = memory.list_namespaces()
    if not namespaces:
        print("(memory is empty)")
    for namespace in namespaces:
        print(f"{namespace}: {memory.count(namespace)} entries")
    memory.close()


def cmd_init(args: argparse.Namespace) -> None:
    root = Path.cwd()
    env_path = root / ".env"
    example_path = root / ".env.example"

    if env_path.exists():
        print(".env already exists - leaving it alone")
    elif example_path.exists():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example - add your ANTHROPIC_AI_KEY")
    else:
        print("No .env.example found here; run this from the MyRuflo project root")

    (root / "workspace").mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    print("Ready. Edit .env, then try: myruflo run \"summarize what's in this workspace\"")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from myruflo.web.app import create_app

    config = load_config()
    if not config.api_key:
        print("WARNING: ANTHROPIC_AI_KEY is not set - chat will be unavailable until it is.")
    app = create_app(config)
    port = int(os.environ.get("PORT", config.web_port))
    uvicorn.run(app, host=config.web_host, port=port)


def cmd_doctor(args: argparse.Namespace) -> None:
    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001 - report any config error to the user
        print(f"FAIL: could not load config: {exc}")
        sys.exit(1)

    problems: list[str] = []

    print(f"workspace: {config.workspace} ({'exists' if config.workspace.is_dir() else 'MISSING'})")
    print(f"data dir:  {config.data_dir} ({'exists' if config.data_dir.is_dir() else 'MISSING'})")
    print(f"shell tool: {'enabled' if config.allow_shell else 'disabled'}")

    if config.api_key:
        print(f"ANTHROPIC_AI_KEY: set (source: {config.api_key_source})")
    else:
        problems.append(
            "ANTHROPIC_AI_KEY is not set (copy .env.example to .env locally, "
            "or bind the MYRUFLO_EVL secret when hosting on GCP)"
        )

    try:
        import anthropic  # noqa: F401

        print("anthropic package: installed")
    except ImportError:
        problems.append("anthropic package not installed (pip install -r requirements.txt)")

    try:
        import numpy  # noqa: F401

        print("numpy package: installed")
    except ImportError:
        problems.append("numpy package not installed (pip install -r requirements.txt)")

    if problems:
        print("\nIssues found:")
        for problem in problems:
            print(f" - {problem}")
        sys.exit(1)

    print("\nAll checks passed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myruflo", description="MyRuflo - a standalone multi-agent AI tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a task through a single agent or an auto-routed swarm")
    run_parser.add_argument("task", help="Natural-language description of the task")
    swarm_group = run_parser.add_mutually_exclusive_group()
    swarm_group.add_argument(
        "--swarm", action="store_true",
        help="Force the full researcher->planner->coder->tester->reviewer pipeline",
    )
    swarm_group.add_argument("--no-swarm", action="store_true", help="Force a single generalist agent")
    run_parser.set_defaults(func=cmd_run)

    memory_parser = subparsers.add_parser("memory", help="Inspect the memory store")
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)

    search_parser = memory_sub.add_parser("search", help="Search a memory namespace")
    search_parser.add_argument("query")
    search_parser.add_argument("--namespace", default="patterns")
    search_parser.add_argument("--top-k", type=int, default=5, dest="top_k")
    search_parser.set_defaults(func=cmd_memory_search)

    list_parser = memory_sub.add_parser("list", help="List memory namespaces and sizes")
    list_parser.set_defaults(func=cmd_memory_list)

    init_parser = subparsers.add_parser("init", help="Create .env and local data/workspace directories")
    init_parser.set_defaults(func=cmd_init)

    doctor_parser = subparsers.add_parser("doctor", help="Check configuration and dependencies")
    doctor_parser.set_defaults(func=cmd_doctor)

    serve_parser = subparsers.add_parser("serve", help="Run the web UI (chat + hidden admin panel)")
    serve_parser.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> None:
    # Model output is unpredictable text (e.g. em dashes); on Windows the
    # default console codepage can't encode it, which would otherwise crash
    # print() mid-run. Fall back to '?' instead of raising.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
