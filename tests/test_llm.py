import asyncio
from types import SimpleNamespace

from buddy_brain.config import Settings
from buddy_brain.llm import OpenAICompatibleProvider


class FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            async def chunks():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Hi"))]
                )
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=" there"))]
                )

            return chunks()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hi there"))]
        )


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_provider_sends_openai_compatible_chat_request():
    client = FakeClient()
    settings = Settings(openai_api_key="test-key")
    provider = OpenAICompatibleProvider(settings=settings, client=client)

    result = asyncio.run(
        provider.complete(
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.2,
        )
    )

    assert result == "Hi there"
    assert client.completions.calls[0]["model"] == "deepseek-v4-flash"
    assert client.completions.calls[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert client.completions.calls[0]["temperature"] == 0.2


def test_provider_stream_yields_text_deltas():
    client = FakeClient()
    settings = Settings(openai_api_key="test-key")
    provider = OpenAICompatibleProvider(settings=settings, client=client)

    async def collect_chunks():
        return [
            chunk
            async for chunk in provider.stream(messages=[{"role": "user", "content": "hello"}])
        ]

    chunks = asyncio.run(collect_chunks())

    assert chunks == ["Hi", " there"]
    assert client.completions.calls[0]["stream"] is True
