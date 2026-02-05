from pydantic import BaseModel

class Config(BaseModel):
    model: str
    auto_run: bool = False
    debug: bool = False
    api_key: str | None = None
    
    @classmethod
    def load(cls):
        import yaml
        from pathlib import Path
        import os

        config_path = Path.home() / ".config" / "bada" / "config.yaml"
        if not config_path.exists():
            return None
        
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
        
        # Load API keys into environment for litellm
        api_keys = data.get("api_keys", {})
        if api_keys.get("openai"):
            os.environ["OPENAI_API_KEY"] = api_keys["openai"]
        if api_keys.get("anthropic"):
            os.environ["ANTHROPIC_API_KEY"] = api_keys["anthropic"]

        telegram_conf = data.get("telegram", {})
        
        return cls(
            model=data.get("default_model", "gpt-4o"),
            auto_run=False,
            telegram_enabled=telegram_conf.get("enabled", False),
            telegram_token=telegram_conf.get("token"),
            telegram_user_id=telegram_conf.get("allowed_user_id")
        )

    telegram_enabled: bool = False
    telegram_token: str | None = None
    telegram_user_id: str | None = None
