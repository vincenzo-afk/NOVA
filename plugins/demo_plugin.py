"""Example JARVIS Plugin."""

from pydantic import BaseModel, Field

PLUGIN_NAME = "hello_world"

class SayHelloArgs(BaseModel):
    name: str = Field(description="The name of the person to greet")

PLUGIN_TOOLS = [
    {
        "name": "plugin.say_hello",
        "description": "Say hello to someone using the example plugin.",
        "fn": "say_hello_fn",
        "schema": SayHelloArgs,
    }
]

def say_hello_fn(name: str) -> dict:
    """Implementation of the plugin.say_hello tool."""
    return {"message": f"Hello {name}, from the Example Plugin!"}
