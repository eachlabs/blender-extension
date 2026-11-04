"""What a chat run is given and gives back: its limits, its result, the executor for Blender's main thread and the 3D generation hooks."""

import threading
from dataclasses import dataclass, field

from .stages import COMPLETE_ROUNDS, EDIT, EDIT_ROUNDS, STAGE_ROUNDS, TOTAL_ROUNDS


@dataclass
class Limits:
    total_rounds: int = TOTAL_ROUNDS
    stage_rounds: dict = field(default_factory=lambda: dict(STAGE_ROUNDS))  # {stage: rounds}
    # Rounds the complete and fix stages may add past the total when planned things are still missing or measured
    # problems remain: the detail stage can use the total up before the check, and the list must still be built.
    extra_rounds: int = 2 * COMPLETE_ROUNDS
    # The most rounds the detail stage may use, from the same rounds as ``extra_rounds``, so the person's limit holds
    # for the whole run; None: the detail stage is not limited (tests, and runs without a limit).
    detail_rounds: object = None
    max_failures: int = 3
    slow_after: float = 15.0
    max_calls_per_reply: int = 8

    def rounds_for(self, stage):
        return self.stage_rounds.get(stage, STAGE_ROUNDS.get(stage, EDIT_ROUNDS if stage == EDIT else COMPLETE_ROUNDS))



@dataclass
class RunResult:
    status: str  # "done" | "stopped" | "cancelled"
    message: str
    rounds: int
    failed_stage: object  # str | None



class StopRun(Exception):
    """Raised by ``execute`` to end the run at once: the model gets no tool result, the bar shows the message."""



class Executor:
    """Runs ``execute`` on another thread (Blender's main thread) and waits for the answer."""

    def __init__(self, call_soon, timeout=30.0, *, execute):
        self._call_soon = call_soon
        self._timeout = timeout
        self._execute = execute

    def __call__(self, name, args):
        done = threading.Event()
        box = {}
        abandoned = threading.Event()

        def job():
            if abandoned.is_set():
                return
            try:
                box["result"] = self._execute(name, args)
            except BaseException as exc:  # handed back to the waiting thread
                box["error"] = exc
            finally:
                done.set()

        self._call_soon(job)
        if not done.wait(self._timeout):
            abandoned.set()
            raise TimeoutError("Blender did not answer in %g s" % self._timeout)
        if "error" in box:
            raise box["error"]
        return box["result"]



@dataclass
class Generation:
    """What a run that may generate 3D objects gives the stage loop. The callables run on the worker thread."""

    stages: tuple = ("layout",)  # the stages told to build the code versions
    brief: str = ""  # added to the request message of those stages: the objects to generate
    notes: object = None  # () -> [str]: objects that failed since the last call; their code versions stay
    complete: bool = False  # after the layout and the check, build the planned things still missing

    def offered(self, stage):
        return stage in self.stages
