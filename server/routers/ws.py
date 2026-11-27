"""WebSocket Realtime Router (/ws/agent/{device_id})."""
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from server.models.database import get_db
from server.models.device import Device
from server.auth.security import decode_jwt_token
from server.services.command_hub import command_hub

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/agent/{device_id}")
async def agent_websocket_endpoint(
    websocket: WebSocket,
    device_id: str,
    db: Session = Depends(get_db),
):
    """Realtime WebSocket endpoint for instant (< 5s) command dispatch and acknowledgements."""
    # 1. Authenticate WebSocket connection
    # Read token from headers or query param 'token'
    token = websocket.query_params.get("token")
    if not token:
        # Check authorization header
        auth_hdr = websocket.headers.get("authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr.split(" ", 1)[1]

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = decode_jwt_token(token)
        token_sub = payload.get("sub")
        token_type = payload.get("type")
        if token_sub != device_id or token_type != "device_access":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Verify device status in DB
    device = db.get(Device, device_id)
    if not device or device.token_revoked:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 2. Connect and register in CommandHub
    await command_hub.connect(device_id, websocket)

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("msg_type")
            if msg_type == "COMMAND_ACK":
                await command_hub.handle_ack(device_id, msg)
    except WebSocketDisconnect:
        await command_hub.disconnect(device_id)
    except Exception:
        await command_hub.disconnect(device_id)
