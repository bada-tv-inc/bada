from rich.console import Console
from rich.prompt import Prompt
from rich.markdown import Markdown
import litellm
from bada.config import Config
import subprocess

console = Console()

class Interpreter:
    def __init__(self, config: Config):
        self.config = config
        self.messages = [
            {"role": "system", "content": self._get_system_prompt()}
        ]

    def _get_system_prompt(self):
        return """
You are an advanced AI interpreter running on a local system.
You can execute code to accomplish tasks.
When you want to execute code, format it as a markdown code block.
Supported languages:
- `bash`: Executed in a subprocess.
- `python`: Executed in a python shell.

Examples:
To list files:
```bash
ls -la
```

To calculate something:
```python
print(2 + 2)
```

ALWAYS parse the output I provide and decide the next step.
If the task is done, simply answer.
"""

    def start_loop(self):
        console.print("[bold yellow]Ready. Type 'exit' to quit.[/bold yellow]")
        
        while True:
            try:
                user_input = Prompt.ask("[bold blue]>[/bold blue]")
                if user_input.lower() in ["exit", "quit"]:
                    break
                
                self.messages.append({"role": "user", "content": user_input})
                self._process_turn()
                
            except KeyboardInterrupt:
                console.print("\n[red]Exiting...[/red]")
                break
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")

    def _process_turn(self):
        content = self._process_turn_and_return()
        console.print(Markdown(content))
        self._execute_code_blocks(content)

    def _process_turn_and_return(self):
        with console.status("[bold green]Thinking...[/bold green]"):
            response = litellm.completion(
                model=self.config.model,
                messages=self.messages
            )
        
        content = response.choices[0].message.content
        self.messages.append({"role": "assistant", "content": content})
        return content

    def _execute_code_blocks(self, content: str):
        # Improved parsing needed here, simplistic version:
        import re
        bash_blocks = re.findall(r"```bash\n(.*?)\n```", content, re.DOTALL)
        python_blocks = re.findall(r"```python\n(.*?)\n```", content, re.DOTALL)
        
        for code in bash_blocks:
            self._run_bash(code)
            
        for code in python_blocks:
            self._run_python(code)

    def _run_bash(self, code):
        if not self.config.auto_run:
            confirm = Prompt.ask(f"[bold red]Execute bash?[/bold red]\n{code}\n(y/n)")
            if confirm.lower() != 'y':
                console.print("[yellow]Skipped.[/yellow]")
                self.messages.append({"role": "user", "content": "User denied execution."})
                return

        try:
            result = subprocess.run(
                code, shell=True, capture_output=True, text=True, executable="/bin/bash"
            )
            output = result.stdout + result.stderr
            console.print(f"[dim]{output}[/dim]")
            self.messages.append({"role": "user", "content": f"Output:\n{output}"})
        except Exception as e:
            self.messages.append({"role": "user", "content": f"Execution Error: {e}"})

    def _run_python(self, code):
        # Safe python execution is hard. For now, simplistic exec().
        if not self.config.auto_run:
            confirm = Prompt.ask(f"[bold red]Execute python?[/bold red]\n{code}\n(y/n)")
            if confirm.lower() != 'y':
                console.print("[yellow]Skipped.[/yellow]")
                self.messages.append({"role": "user", "content": "User denied execution."})
                return
        
        try:
            # Capture stdout hack
            import io, sys
            captured_output = io.StringIO()
            sys.stdout = captured_output
            exec(code, {"__name__": "__main__"})
            sys.stdout = sys.__stdout__
            output = captured_output.getvalue()
            console.print(f"[dim]{output}[/dim]")
            self.messages.append({"role": "user", "content": f"Output:\n{output}"})
        except Exception as e:
            sys.stdout = sys.__stdout__
            self.messages.append({"role": "user", "content": f"Python Error: {e}"})
