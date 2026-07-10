import json

import httpx
import pytest

from buddy_gateway.core_client import BuddyCoreClient, BuddyCoreError


@pytest.mark.asyncio
async def test_buddy_core_client_posts_debug_text_with_device_metadata():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Great! Apple means ping guo.",
                        }
                    }
                ]
            },
        )

    client = BuddyCoreClient(
        base_url="http://buddy-core.local",
        transport=httpx.MockTransport(handler),
    )

    assistant_text = await client.complete_debug_text(
        device_id="fc:01",
        client_id="client-a",
        session_id="session-a",
        text="I like apples",
    )

    assert assistant_text == "Great! Apple means ping guo."
    assert len(requests) == 1
    assert requests[0].url == "http://buddy-core.local/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["stream"] is False
    assert payload["messages"] == [{"role": "user", "content": "I like apples"}]
    assert payload["metadata"] == {
        "device_id": "fc:01",
        "client_id": "client-a",
        "session_id": "session-a",
        "source": "buddy_gateway_debug",
    }


@pytest.mark.asyncio
async def test_buddy_core_client_posts_asr_text_with_turn_metadata():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Nice sentence."}}]},
        )

    client = BuddyCoreClient(
        base_url="http://buddy-core.local",
        transport=httpx.MockTransport(handler),
    )

    assistant_text = await client.complete_text(
        device_id="fc:01",
        client_id="client-a",
        session_id="session-a",
        text="I like apples",
        source="buddy_gateway_asr",
        metadata={"asr_provider": "http_file", "asr_turn_id": "asr-a"},
    )

    assert assistant_text == "Nice sentence."
    payload = json.loads(requests[0].content)
    assert payload["metadata"] == {
        "device_id": "fc:01",
        "client_id": "client-a",
        "session_id": "session-a",
        "source": "buddy_gateway_asr",
        "asr_provider": "http_file",
        "asr_turn_id": "asr-a",
    }


@pytest.mark.asyncio
async def test_buddy_core_client_raises_on_provider_error():
    client = BuddyCoreClient(
        base_url="http://buddy-core.local",
        transport=httpx.MockTransport(lambda request: httpx.Response(502, json={"detail": "bad gateway"})),
    )

    with pytest.raises(BuddyCoreError, match="502"):
        await client.complete_debug_text(
            device_id="fc:01",
            client_id=None,
            session_id="session-a",
            text="hello",
        )
