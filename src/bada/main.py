import typer
from rich.console import Console
from bada.interpreter import Interpreter
from bada.config import Config

app = typer.Typer()
console = Console()

@app.command()
def start(
    model: str = typer.Option("gpt-4o", help="Model to use (e.g., gpt-4o, claude-3-5-sonnet)"),
    auto_run: bool = typer.Option(False, help="Auto-run code without confirmation (DANGEROUS)"),
    debug: bool = typer.Option(False, help="Enable debug mode")
):
    """
    Start bada.
    """
    from bada.onboarding import run_onboarding
    
    # 1. Load Config or Run Onboarding
    config = Config.load()
    if not config:
        run_onboarding()
        config = Config.load() # Reload after setup
        if not config:
            console.print("[red]Configuration failed. Exiting.[/red]")
            return

    # Override config with CLI args
    if model:
        config.model = model
    if auto_run:
        config.auto_run = auto_run
    if debug:
        config.debug = debug

    console.print(f"[bold green]Starting bada[/bold green]")
    console.print(f"[dim]Model: {config.model} | Auto-run: {config.auto_run}[/dim]")

    interpreter = Interpreter(config)

    # 2. Telegram Mode
    if config.telegram_enabled and config.telegram_token:
        from bada.telegram_bot import TelegramBot
        bot = TelegramBot(config, interpreter)
        bot.run()
    else:
        # 3. CLI Mode
        interpreter.start_loop()

@app.command()
def community():
    """
    Open the Bada Community site.
    """
    import webbrowser
    url = "https://bada.io/community"
    console.print(f"[bold green]Opening Bada Community: {url}[/bold green]")
    webbrowser.open(url)

@app.command()
def hyung():
    """
    Talk to a real person (Hyung).
    """
    import webbrowser
    url = "https://hyung.bada.io"
    console.print(f"[bold green]Connecting to Hyung (Human Support):[/bold green] {url}")
    webbrowser.open(url)

@app.command()
def unnie():
    """
    Talk to a real person (Unnie).
    """
    import webbrowser
    url = "https://unnie.bada.io"
    console.print(f"[bold green]Connecting to Unnie (Human Support):[/bold green] {url}")
    webbrowser.open(url)

@app.command()
def security():
    """
    Connect to Security Program (sure.us).
    """
    import webbrowser
    url = "https://sure.us"
    console.print(f"[bold green]Connecting to Security Program:[/bold green] {url}")
    webbrowser.open(url)

@app.command()
def nicesunflower():
    """
    🌻 ?
    """
    import sys
    import subprocess
    from pathlib import Path
    
    # Locate the image file (works for both source and PyInstaller onefile)
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent
        
    image_path = base_path / "easter_egg.jpg"
    
    if image_path.exists():
        console.print("[bold yellow]The sun that makes the ocean sparkle. 🌻🌊[/bold yellow]")
        if sys.platform == "darwin":
            subprocess.run(["open", str(image_path)])
        else:
            subprocess.run(["xdg-open", str(image_path)])
    else:
        console.print("[dim]The sunflower is hiding... (Image file not found)[/dim]")

if __name__ == "__main__":
    app()
