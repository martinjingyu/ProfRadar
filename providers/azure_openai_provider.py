import os
import openai
from .base import LLMProvider


class AzureOpenAIProvider(LLMProvider):
    """
    Azure OpenAI provider.

    Required env vars (or pass to __init__):
        AZURE_OPENAI_API_KEY      — your Azure API key
        AZURE_OPENAI_ENDPOINT     — e.g. https://YOUR_RESOURCE.openai.azure.com/
        AZURE_OPENAI_API_VERSION  — e.g. 2024-02-01
        AZURE_OPENAI_DEPLOYMENT   — your deployment name (used as the model)
    """

    DEFAULT_API_VERSION = "2024-02-01"

    def __init__(
        self,
        deployment: str | None = None,
        api_key: str | None = None,
        endpoint: str | None = None,
        api_version: str | None = None,
    ):
        self._deployment = (
            deployment
            or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
            or "gpt-4o"
        )
        self._client = openai.AzureOpenAI(
            api_key=api_key or os.environ.get("AZURE_OPENAI_API_KEY"),
            azure_endpoint=endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_version=api_version or os.environ.get("AZURE_OPENAI_API_VERSION", self.DEFAULT_API_VERSION),
        )

    @property
    def model_name(self) -> str:
        return f"Azure OpenAI / {self._deployment}"

    def generate(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        response = self._client.chat.completions.create(
            model=self._deployment,   # Azure uses deployment name here
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
