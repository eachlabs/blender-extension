"""The shot video on the bar: its line and pills on the done card in each state with a fake job, and on the status
line while a new chat run goes."""

import threading

from eachlabs import chat_run, jobs, pipeline
from tests.gui_check.bar_input import answer_dialog, bar_point, key, move, placed, viewport_centre
from tests.gui_check.common import check, hold, screenshot, wait_for


def _job(name, state, message="", error="", outputs=(), context=None):
    job = pipeline.REGISTRY.add(jobs.Job("gui-video-%s" % name, "SHOT", "Seedance 2.5", "model",
                                         state=state, message=message, error=error))
    job.outputs, job.context = list(outputs), dict(context or {})
    return job


def _show(job, video=""):
    state = chat_run.STATE
    state.video, state.video_job = video or "rendering", job.job_id
    from eachlabs.chat import make_video

    make_video.sync()


def video_flow():
    """Run on the open done card of a chat whose camera moves: the video's line and its pills in each state, with a
    fake job."""
    from eachlabs import overlay

    state = chat_run.STATE
    look = _job("look", jobs.RUNNING, "Making the look (1 of 2)")
    _show(look)
    overlay.tag_redraw()
    yield 0.6
    check("video: while it is made the done card shows its line with Stop video",
          "Video: making the look (1 of 2)…" in placed()[4].reply and "video_stop" in placed()[1].hits,
          "%r %s" % (placed()[4].reply, sorted(placed()[1].hits)))
    screenshot("video-01-making.png")

    done = _job("done", jobs.DONE, outputs=[("/nonexistent/video.mp4", "video")])
    _show(done, "done")
    overlay.tag_redraw()
    yield 0.6
    check("video: a made video's line says it is in the Video Sequencer, with Show file",
          "Video: in the Video Sequencer" in placed()[4].reply and "video_file" in placed()[1].hits,
          "%r %s" % (placed()[4].reply, sorted(placed()[1].hits)))

    failed = _job("failed", jobs.FAILED, error="Photo 1 failed: the photo was refused", context={"shot": {}})
    _show(failed)
    overlay.tag_redraw()
    yield 0.6
    check("video: a failed video's line says why, with Retry video",
          "Video failed: Photo 1 failed: the photo was refused" in placed()[4].reply
          and "video_retry" in placed()[1].hits, placed()[4].reply)
    screenshot("video-02-failed.png")

    state.video, state.video_job, state.video_info, state.video_stage = "", "", {}, ""
    for job in (look, done, failed):
        pipeline.REGISTRY.jobs.pop(job.job_id, None)
    overlay.tag_redraw()  # the card loses its video pills: the next clicks need the new layout's hits
    yield 0.6
    check("video: without a video the card has no video pills",
          not [a for a in placed()[4].actions if a.startswith("video")], str(placed()[4].actions))
    move(*viewport_centre())
    key("ESC")  # the bar gives the keys back, as the person's next edit expects
    yield 0.4


_DURING = {}  # the fake video job made before the chat run that ``during_run`` checks, and the run's gate


def before_run(client):
    """A video being made when a new chat run is sent from the done card. The run's model waits at its first call
    until ``during_run`` has checked the running bar."""
    _DURING["job"] = job = _job("during-run", jobs.RUNNING, "Seedance 2.5 is making it")
    _show(job)
    gate = _DURING["gate"] = threading.Event()
    llm = client.chat_llm
    model = type(llm)

    class Gated(model):
        def __call__(self, messages, tools):
            if not gate.is_set():
                hold(60, gate)
            return model.__call__(self, messages, tools)

    llm.__class__ = Gated
    _DURING["llm"] = (llm, model)
    yield 0.2


def during_run():
    """While the chat runs, the video's line sits on the bar's status line with Stop, and follows the job on the
    main thread's tick; when the run is done, the done card shows it again with its buttons."""
    from eachlabs import overlay

    job = _DURING.pop("job", None)
    if job is None:
        return
    gate, (llm, model) = _DURING.pop("gate"), _DURING.pop("llm")
    try:
        seen = yield from wait_for(lambda: chat_run.STATE.running and placed()[4].objects[-1:] != []
                                   and placed()[4].objects[-1].startswith("Video: Seedance 2.5 is making it…")
                                   and "video_stop" in placed()[1].hits, 10)
        check("video: a new chat run keeps the video; its line and Stop show on the bar's status line",
              seen and chat_run.STATE.video_job == job.job_id,
              "%s %s %s" % (placed()[4].mode, placed()[4].objects, sorted(placed()[1].hits)))
        screenshot("video-09-status-line.png")
        opened = yield from answer_dialog(bar_point("video_stop"), "Stop the video?", True)
        check("video: Stop on the status line asks first and cancels the video while the chat runs",
              opened and job.cancel_event.is_set() and chat_run.STATE.running, "%s %s" % (opened, job.message))
        job.apply({"state": jobs.CANCELLED, "message": "Cancelled"})  # what the worker answers to the cancel
        stopped = yield from wait_for(lambda: placed()[4].objects[-1:] == [
            "Video stopped; it may still be billed · Retry when the chat finishes."], 10)
        check("video: the status line says the video stopped and when Retry comes back", stopped and chat_run.STATE.running,
              str(placed()[4].objects))
        pipeline.REGISTRY.jobs.pop(job.job_id, None)
        job = _job("during-run-2", jobs.RUNNING, "Seedance 2.5 is making it")
        _show(job)
        job.apply({"state": jobs.DONE, "message": "Strip on channel 2"})  # the video lands while the chat runs
        moved = yield from wait_for(lambda: chat_run.STATE.running
                                    and placed()[4].objects[-1:] == ["Video: in the Video Sequencer"]
                                    and "video_file" in placed()[1].hits, 10)
        check("video: the status line follows the job on the tick, with Show file", moved,
              "%s %s %s" % (chat_run.STATE.running, placed()[4].objects, sorted(placed()[1].hits)))
        screenshot("video-10-status-line-done.png")
    finally:
        gate.set()
        llm.__class__ = model
    yield from wait_for(lambda: not chat_run.STATE.running, 40)
    overlay.tag_redraw()
    yield 0.6
    check("video: once the run is done, its card shows the video again with Show file",
          "Video: in the Video Sequencer" in placed()[4].reply and "video_file" in placed()[1].hits,
          "%r %s" % (placed()[4].reply, sorted(placed()[1].hits)))
    chat_run.STATE.video, chat_run.STATE.video_job = "", ""
    pipeline.REGISTRY.jobs.pop(job.job_id, None)
    overlay.tag_redraw()  # the card loses its video pills: the next clicks need the new layout's hits
    yield 0.6
