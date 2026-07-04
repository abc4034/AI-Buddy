from pathlib import Path

from fastapi.testclient import TestClient

from buddy_gateway.app import create_http_app, create_websocket_app
from buddy_gateway.audio_store import AudioArtifactStore
from buddy_gateway.config import GatewaySettings
from buddy_gateway.state import GatewayState


class FakeBuddyCoreClient:
    def __init__(self, assistant_text: str = "Sure! Apples are red.") -> None:
        self.assistant_text = assistant_text
        self.calls = []

    async def complete_debug_text(self, *, device_id, client_id, session_id, text):
        self.calls.append(
            {
                "device_id": device_id,
                "client_id": client_id,
                "session_id": session_id,
                "text": text,
            }
        )
        return self.assistant_text


class FailingBuddyCoreClient:
    async def complete_debug_text(self, *, device_id, client_id, session_id, text):
        raise RuntimeError("buddy core unavailable")


def test_gateway_ota_get_returns_xiaozhi_style_text_health():
    settings = GatewaySettings(advertise_host="192.168.0.101", http_port=18003, websocket_port=18000)
    state = GatewayState()
    client = TestClient(create_http_app(settings=settings, state=state))

    response = client.get("/xiaozhi/ota/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "OTA" in response.text
    assert "ws://192.168.0.101:18000/xiaozhi/v1/" in response.text


def test_gateway_ota_post_returns_compatible_websocket_payload():
    settings = GatewaySettings(advertise_host="192.168.0.101", http_port=18003, websocket_port=18000)
    state = GatewayState()
    client = TestClient(create_http_app(settings=settings, state=state))

    response = client.post(
        "/xiaozhi/ota/",
        headers={"device-id": "fc:01", "client-id": "client-a"},
        json={"board": {"type": "esp32-s3"}, "version": "1.2.3"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["server_time"]["timestamp"], int)
    assert payload["server_time"]["timezone_offset"] == 480
    assert payload["firmware"]["version"] == "1.2.3"
    assert payload["firmware"]["url"] == ""
    assert payload["websocket"]["url"] == "ws://192.168.0.101:18000/xiaozhi/v1/"
    assert payload["websocket"]["token"] == ""
    assert payload["message"] == "Buddy Device Gateway is running."

    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["http_port"] == 18003
    assert health["websocket_port"] == 18000
    assert health["recent_devices"] == 1


def test_gateway_ota_post_accepts_firmware_application_version_shape():
    settings = GatewaySettings(advertise_host="192.168.0.101", http_port=18003, websocket_port=18000)
    state = GatewayState()
    client = TestClient(create_http_app(settings=settings, state=state))

    response = client.post(
        "/xiaozhi/ota/",
        headers={"device-id": "fc:01"},
        json={
            "application": {"version": "2.2.6"},
            "board": {"type": "bread-compact-wifi-lcd"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["firmware"]["version"] == "2.2.6"
    assert state.ota_summaries()[0]["version"] == "2.2.6"


def test_gateway_ota_post_prefers_xiaozhi_version_headers_over_body():
    settings = GatewaySettings(advertise_host="192.168.0.101", http_port=18003, websocket_port=18000)
    state = GatewayState()
    client = TestClient(create_http_app(settings=settings, state=state))

    response = client.post(
        "/xiaozhi/ota/",
        headers={"device-id": "fc:01", "firmware-version": "3.1.4"},
        json={
            "version": "1.2.3",
            "application": {"version": "2.2.6"},
            "board": {"type": "bread-compact-wifi-lcd"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["firmware"]["version"] == "3.1.4"
    assert state.ota_summaries()[0]["version"] == "3.1.4"


def test_gateway_websocket_records_text_messages_and_audio_bytes(tmp_path: Path):
    settings = GatewaySettings(
        advertise_host="127.0.0.1",
        http_port=18003,
        websocket_port=18000,
        audio_artifact_dir=str(tmp_path),
    )
    state = GatewayState()
    audio_store = AudioArtifactStore(base_dir=tmp_path)
    client = TestClient(create_websocket_app(settings=settings, state=state, audio_store=audio_store))

    with client.websocket_connect(
        "/xiaozhi/v1/",
        headers={"device-id": "fc:01", "client-id": "client-a"},
    ) as websocket:
        websocket.send_json(
            {
                "type": "hello",
                "version": 1,
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }
        )
        welcome = websocket.receive_json()
        assert welcome["type"] == "hello"
        assert welcome["transport"] == "websocket"
        assert welcome["session_id"]
        assert welcome["audio_params"]["sample_rate"] == 16000

        websocket.send_json({"type": "listen", "state": "start", "mode": "manual"})
        websocket.send_json({"type": "ping", "timestamp": 123})
        pong = websocket.receive_json()
        assert pong["type"] == "pong"
        websocket.send_json({"type": "abort"})
        websocket.send_json({"type": "mcp", "payload": {"name": "debug"}})
        websocket.send_bytes(b"\x01\x02\x03\x04")

    summaries = state.session_summaries()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["device_id"] == "fc:01"
    assert summary["client_id"] == "client-a"
    assert summary["message_counts"]["hello"] == 1
    assert summary["message_counts"]["listen"] == 1
    assert summary["message_counts"]["ping"] == 1
    assert summary["message_counts"]["abort"] == 1
    assert summary["message_counts"]["mcp"] == 1
    assert summary["last_listen_state"] == "start"
    assert summary["audio_frame_count"] == 1
    assert summary["audio_byte_count"] == 4
    assert summary["disconnected_at"] is not None


def test_gateway_debug_sessions_endpoint_shares_websocket_state():
    settings = GatewaySettings(advertise_host="127.0.0.1", http_port=18003, websocket_port=18000)
    state = GatewayState()
    websocket_client = TestClient(create_websocket_app(settings=settings, state=state))
    http_client = TestClient(create_http_app(settings=settings, state=state))

    with websocket_client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "device-b"}):
        pass

    payload = http_client.get("/debug/sessions").json()
    assert payload["session_count"] == 1
    assert payload["sessions"][0]["device_id"] == "device-b"


def test_gateway_http_inject_text_calls_buddy_core_with_device_metadata():
    settings = GatewaySettings(advertise_host="127.0.0.1", http_port=18003, websocket_port=18000)
    state = GatewayState()
    core_client = FakeBuddyCoreClient(assistant_text="Great! Apple means ping guo.")
    websocket_client = TestClient(create_websocket_app(settings=settings, state=state, core_client=core_client))
    http_client = TestClient(create_http_app(settings=settings, state=state, core_client=core_client))

    with websocket_client.websocket_connect(
        "/xiaozhi/v1/",
        headers={"device-id": "fc:01", "client-id": "client-a"},
    ) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]

    response = http_client.post(
        f"/debug/sessions/{session_id}/inject-text",
        json={"text": "I like apples"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["session_id"] == session_id
    assert payload["device_id"] == "fc:01"
    assert payload["client_id"] == "client-a"
    assert payload["user_text"] == "I like apples"
    assert payload["assistant_text"] == "Great! Apple means ping guo."
    assert core_client.calls == [
        {
            "device_id": "fc:01",
            "client_id": "client-a",
            "session_id": session_id,
            "text": "I like apples",
        }
    ]
    assert state.session_summaries()[0]["debug_turns"][0]["assistant_text"] == "Great! Apple means ping guo."


def test_gateway_websocket_debug_text_returns_result_to_debug_client_only():
    settings = GatewaySettings(advertise_host="127.0.0.1", http_port=18003, websocket_port=18000)
    state = GatewayState()
    core_client = FakeBuddyCoreClient(assistant_text="Hello from Buddy Core.")
    client = TestClient(create_websocket_app(settings=settings, state=state, core_client=core_client))

    with client.websocket_connect(
        "/xiaozhi/v1/",
        headers={"device-id": "fc:01", "client-id": "client-a"},
    ) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]
        websocket.send_json({"type": "debug_text", "text": "hello buddy"})
        result = websocket.receive_json()

    assert result["type"] == "debug_text_result"
    assert result["status"] == "ok"
    assert result["session_id"] == session_id
    assert result["assistant_text"] == "Hello from Buddy Core."
    assert core_client.calls[0]["text"] == "hello buddy"
    assert state.session_summaries()[0]["message_counts"]["debug_text"] == 1


def test_gateway_inject_text_validates_empty_and_unknown_session():
    settings = GatewaySettings(advertise_host="127.0.0.1", http_port=18003, websocket_port=18000)
    state = GatewayState()
    core_client = FakeBuddyCoreClient()
    websocket_client = TestClient(create_websocket_app(settings=settings, state=state, core_client=core_client))
    http_client = TestClient(create_http_app(settings=settings, state=state, core_client=core_client))

    with websocket_client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01"}) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]

    empty_response = http_client.post(f"/debug/sessions/{session_id}/inject-text", json={"text": "   "})
    unknown_response = http_client.post("/debug/sessions/missing-session/inject-text", json={"text": "hello"})

    assert empty_response.status_code == 400
    assert unknown_response.status_code == 404
    assert core_client.calls == []


def test_gateway_inject_text_records_buddy_core_failure():
    settings = GatewaySettings(advertise_host="127.0.0.1", http_port=18003, websocket_port=18000)
    state = GatewayState()
    core_client = FailingBuddyCoreClient()
    websocket_client = TestClient(create_websocket_app(settings=settings, state=state, core_client=core_client))
    http_client = TestClient(create_http_app(settings=settings, state=state, core_client=core_client))

    with websocket_client.websocket_connect("/xiaozhi/v1/", headers={"device-id": "fc:01"}) as websocket:
        websocket.send_json({"type": "hello"})
        session_id = websocket.receive_json()["session_id"]

    response = http_client.post(f"/debug/sessions/{session_id}/inject-text", json={"text": "hello"})

    assert response.status_code == 502
    summary = state.session_summaries()[0]
    assert summary["debug_turns"][0]["status"] == "error"
    assert "buddy core unavailable" in summary["debug_turns"][0]["error"]


def test_gateway_settings_allow_host_and_port_overrides():
    settings = GatewaySettings(
        host="127.0.0.1",
        advertise_host="10.0.0.5",
        http_port=28003,
        websocket_port=28000,
    )

    assert settings.websocket_url() == "ws://10.0.0.5:28000/xiaozhi/v1/"
