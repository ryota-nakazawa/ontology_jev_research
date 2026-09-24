"""Bounded experiment progress: jitter and revisiting old ground are not progress."""
from dataclasses import dataclass


@dataclass
class ProgressGuard:
    anchor_x: int
    min_progress: int = 8
    decision_limit: int = 12
    frame_limit: int = 180
    last_progress_frame: int = 0
    decisions_without_progress: int = 0
    frame: int = 0
    recovery_attempted: bool = False

    def observe(self, best_x: int, frame: int) -> None:
        self.frame = frame
        if best_x >= self.anchor_x + self.min_progress:
            self.anchor_x = best_x
            self.last_progress_frame = frame
            self.decisions_without_progress = 0
        else:
            self.decisions_without_progress += 1

    @property
    def stalled(self) -> bool:
        return (self.decisions_without_progress >= self.decision_limit
                or self.frame - self.last_progress_frame >= self.frame_limit)

    @property
    def can_recover(self) -> bool:
        return not self.recovery_attempted

    def begin_recovery(self) -> None:
        self.recovery_attempted = True

    def details(self) -> dict:
        return {'anchor_x': self.anchor_x,
                'minimum_progress_pixels': self.min_progress,
                'decisions_without_progress': self.decisions_without_progress,
                'frames_without_progress': self.frame - self.last_progress_frame,
                'recovery_attempted': self.recovery_attempted}
