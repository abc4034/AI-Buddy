from fastapi.testclient import TestClient

from buddy_gateway.app import create_http_app, create_websocket_app
from buddy_gateway.config import GatewaySettings
from buddy_gateway.state import GatewayState


def test_gateway_ota_get_returns_compatible_websocket_payload():
    settings = GatewaySettings(advertise_host="192.168.0.101", http_port=18003, websocket_port=18000)
    state = GatewayState()
    client = TestClient(create_http_app(settings=settings, state=state))

    response = client.get("/xiaozhi/ota/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["websocket"]["url"] == "ws://192.168.0.101:18000/xiaozhi/v1/"
    assert payload["firmware"]["url"] == ""
    assert payload["message"] == "Buddy Device Gateway v0.1 is running."


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


def test_gateway_websocket_records_text_messages_and_audio_bytes():
    settings = GatewaySettings(advertise_host="127.0.0.1", http_port=18003, websocket_port=18000)
    state = GatewayState()
    client = TestClient(create_websocket_app(settings=settings, state=state))

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


def test_gateway_settings_allow_host_and_port_overrides():
    settings = GatewaySettings(
        host="127.0.0.1",
        advertise_host="10.0.0.5",
        http_port=28003,
        websocket_port=28000,
    )

    assert settings.websocket_url() == "ws://10.0.0.5:28000/xiaozhi/v1/"
