import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
import yaml
import os
from pathlib import Path

console = Console()

def run_onboarding():
    console.print(Panel.fit(
        "[bold magenta]Welcome to bada[/bold magenta]\n"
        "[dim]Created by bada & nicesunflower[/dim]",
        border_style="magenta"
    ))

    config_dir = Path.home() / ".config" / "bada"
    config_path = config_dir / "config.yaml"
    
    if config_path.exists():
        if not Confirm.ask("Configuration found. Do you want to reconfigure?"):
            return

    # Community Promotion
    console.print("\n[bold yellow]Join the Bada Community![/bold yellow]")
    console.print("Connect with other users and get support.")
    if Confirm.ask("Open community site now?", default=True):
         import webbrowser
         webbrowser.open("https://bada.ai/community")

    console.print("\n[bold cyan]Let's set up your environment.[/bold cyan]")
    
    # 1. LLM API Keys
    console.print("\n[bold]1. API Keys[/bold]")
    console.print("To use this tool, you need an API key for your preferred LLM provider.")
    openai_key = Prompt.ask("Enter OpenAI API Key (optional)", password=True, default="")
    anthropic_key = Prompt.ask("Enter Anthropic API Key (optional)", password=True, default="")

    # 2. Telegram Setup
    console.print("\n[bold]2. Telegram Integration (Optional)[/bold]")
    console.print("Control your computer remotely via Telegram.")
    enable_telegram = Confirm.ask("Do you want to enable Telegram integration?")
    
    telegram_token = ""
    telegram_user_id = ""
    
    if enable_telegram:
        console.print("1. Create a bot with [bold]@BotFather[/bold] and get the Token.")
        telegram_token = Prompt.ask("Enter Telegram Bot Token")
        
        console.print("2. Get your User ID from [bold]@userinfobot[/bold].")
        telegram_user_id = Prompt.ask("Enter your Telegram User ID")

    # Save Config
    config_data = {
        "api_keys": {
            "openai": openai_key,
            "anthropic": anthropic_key
        },
        "telegram": {
            "enabled": enable_telegram,
            "token": telegram_token,
            "allowed_user_id": telegram_user_id
        }
    }

    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)
        
    console.print(f"\n[bold green]Configuration saved to {config_path}![/bold green]")
    console.print("You are ready to go.")
