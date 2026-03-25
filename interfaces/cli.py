"""Rich terminal interface with streamed tokens."""

from __future__ import annotations

HAS_RICH = True
try:
    from rich.console import Console
except Exception:  # pragma: no cover
    HAS_RICH = False

    class Console:  # type: ignore[override]
        def print(self, *args, end="\n", **kwargs):
            _ = kwargs
            print(*args, end=end)

        def input(self, prompt: str) -> str:
            return input(prompt)


def run_cli(agent) -> None:
    console = Console()
    banner = "[bold cyan]JARVIS CLI[/bold cyan]  Type /exit to quit" if HAS_RICH else "JARVIS CLI  Type /exit to quit"
    console.print(banner)

    while True:
        prompt = "\n[bold green]You[/bold green] > " if HAS_RICH else "\nYou > "
        user_text = console.input(prompt).strip()
        if not user_text:
            continue
        if user_text in {"/exit", "/quit"}:
            console.print("[yellow]Goodbye.[/yellow]" if HAS_RICH else "Goodbye.")
            return
        if user_text == "/reset":
            agent.reset_context()
            msg = "[yellow]Context reset. Memories kept.[/yellow]" if HAS_RICH else "Context reset. Memories kept."
            console.print(msg)
            continue
        if user_text.startswith("/session "):
            name = user_text.split(" ", 1)[1].strip()
            if name:
                state = agent.switch_session(name)
                msg = (
                    f"[cyan]Switched to session:[/cyan] {state.name} ({state.session_id})"
                    if HAS_RICH
                    else f"Switched to session: {state.name} ({state.session_id})"
                )
                console.print(msg)
                continue
        if user_text == "/status":
            console.print(agent.status_text())
            continue

        console.print("[bold magenta]JARVIS[/bold magenta] > " if HAS_RICH else "JARVIS > ", end="")
        chunks = []
        for token in agent.ask_stream(user_text):
            chunks.append(token)
            console.print(token, end="")

        if not chunks:
            console.print("(no output)", end="")

        provider_msg = f"\n[dim][{agent.last_provider_label()}][/dim]" if HAS_RICH else f"\n[{agent.last_provider_label()}]"
        console.print(provider_msg)
