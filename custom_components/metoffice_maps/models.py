"""Data shared between the coordinator, sensors and HTTP view."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util


@dataclass(slots=True, frozen=True)
class Frame:
    """One published frame. Valid time comes from the fileId: run plus step."""

    file_id: str
    step: int
    run: datetime

    @property
    def valid_time(self) -> datetime:
        """Return when this frame is valid."""
        return self.run + timedelta(hours=self.step)

    def as_state(self) -> dict[str, object]:
        """Return the frame for storage."""
        return {"file_id": self.file_id, "step": self.step, "run": self.run.isoformat()}

    @classmethod
    def from_state(cls, data: dict[str, object]) -> Frame:
        """Return a frame from storage."""
        run = dt_util.parse_datetime(str(data["run"]))
        assert run is not None
        return cls(str(data["file_id"]), int(data["step"]), run)  # type: ignore[call-overload]


@dataclass(slots=True)
class ForecastData:
    """What the coordinator publishes after each poll."""

    frames: list[Frame] = field(default_factory=list)
    last_checked: datetime | None = None
    last_error: str | None = None

    @property
    def run(self) -> datetime | None:
        """Return the model run the frames come from."""
        return self.frames[0].run if self.frames else None

    def frame(self, step: int) -> Frame | None:
        """Return the published frame for a step."""
        return next((frame for frame in self.frames if frame.step == step), None)
