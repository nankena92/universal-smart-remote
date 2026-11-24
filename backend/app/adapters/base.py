from __future__ import annotations
import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

class RemoteKey(str, enum.Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    OK = "ok"
    BACK = "back"
    HOME = "home"
    MENU = "menu"
    POWER = "power"
    VOLUME_UP = "volume-up"
    VOLUME_DOWN = "volume-down"
    MUTE = "mute"
    CHANNEL_UP = "channel-up"
    CHANNEL_DOWN = "channel-down"
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    REWIND = "rewind"
    FAST_FORWARD = "fast-forward"

@dataclass
class CommandResult:
    success: bool
    message: str = ""
    error: Optional[str] = None
    details: dict = field(default_factory=dict)

@dataclass
class DeviceInfo:
    id: str
    name: str
    brand: str          # one of BRANDS keys below
    model: str = ""
    ip: str = ""
    port: int = 0
    mac: str = ""
    pairing_token: str = ""
    paired: bool = False

class TvAdapter(ABC):
    brand: str = ""

    def __init__(self, device: DeviceInfo):
        self.device = device
        self.connected = False

    @abstractmethod
    async def connect(self) -> CommandResult: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_key(self, key: RemoteKey) -> CommandResult: ...

    @abstractmethod
    async def launch_app(self, app_id: str) -> CommandResult: ...

    def supports(self, feature: str) -> bool:
        """feature in: power, volume, mute, channel, media, launch_app, pairing."""
        return True

    async def get_status(self) -> dict:
        return {"brand": self.brand, "connected": self.connected, "ip": self.device.ip}
