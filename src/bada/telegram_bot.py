from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from bada.config import Config
from bada.interpreter import Interpreter
import asyncio
import io
import sys
from rich.console import Console

console = Console()

class TelegramBot:
    def __init__(self, config: Config, interpreter: Interpreter):
        self.config = config
        self.interpreter = interpreter
        self.app = ApplicationBuilder().token(config.telegram_token).build()

    def run(self):
        console.print(f"[bold green]Starting Telegram Bot...[/bold green]")
        
        # Handlers
        start_handler = CommandHandler('start', self._start)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_message)
        
        self.app.add_handler(start_handler)
        self.app.add_handler(message_handler)
        
        self.app.run_polling()

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_user.id) != str(self.config.telegram_user_id):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⛔ Unauthorized access.")
            return
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="👋 Hello! I am bada.\nCreated by bada & nicesunflower.\nSend me a command!"
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_user.id) != str(self.config.telegram_user_id):
            return

        user_input = update.message.text
        chat_id = update.effective_chat.id

        # Notify user we are thinking
        status_msg = await context.bot.send_message(chat_id=chat_id, text="Thinking...")

        # Hook Interpreter Output
        # This is a tricky part: Interpreter is designed for CLI sync loop.
        # For MVP, we will instantiate a fresh turn here or refactor Interpreter to be async.
        # Given the constraints, let's try to run a single turn and capture output.
        
        self.interpreter.messages.append({"role": "user", "content": user_input})
        
        # Capture stdout to redirect to Telegram
        captured_output = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = captured_output
        
        try:
            # We need to make Interpreter._process_turn return the response instead of just printing
            # For now, we rely on the fact it prints to console.
            # Ideally Interpreter should be refactored to return strings.
            response_content = self.interpreter._process_turn_and_return() 
            
            # Execute code blocks if any (Auto-run assumed for Telegram or need explicit confirm flow)
            # For this MVP, we will be safer and ONLY run if auto_run is True or mock confirmation.
            # Real remote control needs a conversational loop.
            
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")
            sys.stdout = original_stdout
            return

        sys.stdout = original_stdout
        output_log = captured_output.getvalue()
        
        # Send LLM response
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=response_content)
        
        # Send Execution Logs
        if output_log.strip():
            await context.bot.send_message(chat_id=chat_id, text=f"Logs:\n{output_log}")
