"""In-process portal page. Tests do not open a browser or a socket."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

from flask.testing import FlaskClient
from PIL import Image, ImageDraw

from services.legacy_portal.app import create_app


@dataclass
class Snapshot:
    url: str
    status: int
    text: str
    fields: dict[str, str]


@dataclass
class FlaskPage:
    client: FlaskClient
    pending: dict[str, str] = field(default_factory=dict)
    url: str = "/"

    def goto(self, path: str) -> Snapshot:
        if not path.startswith("/"):
            raise PermissionError("only portal paths are allowed")
        self.url = path
        response = self.client.get(path)
        return self._snap(response.status_code, response.get_data(as_text=True))

    def fill(self, name: str, value: str) -> None:
        if name == "trap":
            raise PermissionError("the hidden field is not an instruction")
        self.pending[name] = value

    def submit(self, path: str) -> Snapshot:
        if not path.startswith("/"):
            raise PermissionError("only portal paths are allowed")
        self.url = path
        response = self.client.post(path, data=self.pending)
        return self._snap(response.status_code, response.get_data(as_text=True))

    def screenshot(self, label: str) -> bytes:
        image = Image.new("L", (320, 48), 255)
        ImageDraw.Draw(image).text((4, 16), label[:48], fill=0)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _snap(self, status: int, text: str) -> Snapshot:
        fields: dict[str, str] = {}
        for name in ("note", "adjuster_note", "user", "password"):
            if f"name='{name}'" in text or f'name="{name}"' in text:
                fields[name] = ""
        if "id='saved'" in text:
            fields["saved"] = text.split("id='saved'>", 1)[1].split("</p>", 1)[0]
        if "id='pending'" in text:
            fields["pending"] = text.split("id='pending'>", 1)[1].split("</p>", 1)[0]
        return Snapshot(self.url, status, text, fields)


def open_portal() -> FlaskPage:
    return FlaskPage(create_app().test_client())
