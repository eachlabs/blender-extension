import types
import unittest

from eachlabs import jobs
from eachlabs.chat import video_track


def job(state, message="", error=""):
    return types.SimpleNamespace(job_id="j1", state=state, message=message, error=error)


def chat(**kw):
    values = dict(video="", video_job="j1", video_message="", video_seconds=0, video_progress=0, video_since=0.0,
                  video_stage="", video_info={})
    values.update(kw)
    return types.SimpleNamespace(**values)


class StageTest(unittest.TestCase):
    def test_each_job_state_maps_to_a_stage_chip(self):
        cases = [
            (jobs.RENDERING, "Recording the camera move", "camera"),
            (jobs.RENDERING, "Waiting for the scene chat to finish", "camera"),
            (jobs.RENDERING, "Rendering the key frames", "keys"),
            (jobs.UPLOADING, "Uploading 3 file(s)", "look"),
            (jobs.RUNNING, "Making the look (2 of 3)", "look"),
            (jobs.RUNNING, "Seedance 2.5 is making it", "video"),
            (jobs.SUBMITTING, "", "video"),
            (jobs.DOWNLOADING, "", "video"),
            (jobs.IMPORTING, "", "sequencer"),
            (jobs.DONE, "Strip on channel 2", ""),
            (jobs.FAILED, "", ""),
            (jobs.CANCELLED, "Cancelled", ""),
        ]
        for state, message, stage in cases:
            with self.subTest(state, message=message):
                self.assertEqual(video_track.stage_of(state, message), stage)

    def test_a_failed_or_stopped_job_keeps_the_stage_it_reached_and_its_end_time(self):
        c = chat(video_info={"started": 1.0})
        video_track.copy(c, job(jobs.RUNNING, "Making the look (1 of 2)"), now=10.0)
        self.assertEqual(c.video_stage, "look")
        video_track.copy(c, job(jobs.FAILED, error="Photo 1 failed: refused"), now=12.0)
        self.assertEqual((c.video, c.video_stage, c.video_info["ended"]), ("failed", "look", 12.0))
        video_track.copy(c, job(jobs.FAILED, error="Photo 1 failed: refused"), now=20.0)
        self.assertEqual(c.video_info["ended"], 12.0)  # the first time it ended


class CopyTest(unittest.TestCase):
    def test_each_job_state_becomes_a_bar_state(self):
        cases = [
            (job(jobs.RENDERING, "Recording the camera move"), "rendering", ""),
            (job(jobs.UPLOADING, "Uploading 3 file(s)"), "photos", ""),
            (job(jobs.RUNNING, "Making the look (2 of 3)"), "photos", "2 of 3"),
            (job(jobs.RUNNING, "Seedance 2.5 is making it"), "generating", ""),
            (job(jobs.DOWNLOADING), "generating", ""),
            (job(jobs.IMPORTING), "generating", ""),
            (job(jobs.DONE, "Strip on channel 2"), "done", ""),
            (job(jobs.FAILED, error="The provider said no."), "failed", "The provider said no"),
            (job(jobs.CANCELLED, "Cancelled"), "stopped", ""),
        ]
        for found, video, message in cases:
            with self.subTest(found.state, message=found.message):
                c = chat()
                video_track.copy(c, found, now=10.0, progress=40)
                self.assertEqual((c.video, c.video_message), (video, message))
        c = chat()
        video_track.copy(c, job(jobs.RENDERING), now=10.0, progress=40)
        self.assertEqual(c.video_progress, 40)

    def test_generating_counts_from_when_it_started(self):
        c = chat()
        video_track.copy(c, job(jobs.RUNNING, "Seedance 2.5 is making it"), now=100.0)
        video_track.copy(c, job(jobs.RUNNING, "Seedance 2.5 is making it"), now=180.4)
        self.assertEqual(c.video_seconds, 80)

    def test_a_job_that_is_gone_ends_a_running_video_and_clears_a_finished_one(self):
        c = chat(video="generating")
        video_track.copy(c, None, now=1.0)
        self.assertEqual((c.video, c.video_message, c.video_job), ("failed", video_track.GONE, ""))
        c = chat(video="done")
        video_track.copy(c, None, now=1.0)  # Open Sequencer and Show file need the job: Make video stays
        self.assertEqual((c.video, c.video_job), ("", ""))
        c = chat(video="", video_job="")
        video_track.copy(c, None, now=1.0)
        self.assertEqual(c.video, "")

    def test_forget_clears_the_video(self):
        c = chat(video="failed", video_message="Photo 1 failed: no", video_seconds=40, video_progress=80,
                 video_since=12.0)
        video_track.forget(c)
        self.assertEqual((c.video, c.video_job, c.video_message, c.video_seconds, c.video_progress, c.video_since),
                         ("", "", "", 0, 0, 0.0))

    def test_progress_from_files(self):
        self.assertEqual(video_track.progress(clip_frames=90, clip_written=45, clip_done=False, keys=3, keys_written=0),
                         48)  # 45 of 93 pictures
        self.assertEqual(video_track.progress(90, 12, True, 3, 3), 100)
        self.assertEqual(video_track.progress(0, 0, False, 0, 0), 0)


class Registry:
    def __init__(self, *found):
        self.jobs = {j.job_id: j for j in found}

    def get(self, job_id):
        return self.jobs.get(job_id)


class FollowTest(unittest.TestCase):
    def test_it_copies_the_job_and_says_when_the_line_changed(self):
        c = chat(video="rendering")
        found = job(jobs.RUNNING, "Making the look (1 of 2)")
        self.assertTrue(video_track.follow(c, Registry(found), now=5.0))
        self.assertEqual((c.video, c.video_message), ("photos", "1 of 2"))
        self.assertFalse(video_track.follow(c, Registry(found), now=6.0))  # nothing new: no redraw
        found.message = "Seedance 2.5 is making it"
        self.assertTrue(video_track.follow(c, Registry(found), now=10.0))
        self.assertFalse(video_track.follow(c, Registry(found), now=10.5))
        self.assertTrue(video_track.follow(c, Registry(found), now=11.0))  # the clock moved a second
        self.assertEqual(c.video_seconds, 1)

    def test_no_video_is_left_alone(self):
        c = chat(video="failed", video_job="", video_message="no camera")
        self.assertFalse(video_track.follow(c, Registry(), now=1.0))
        self.assertEqual((c.video, c.video_message), ("failed", "no camera"))

    def test_rendering_progress_counts_the_written_files(self):
        import os
        import tempfile

        folder = tempfile.mkdtemp()
        clip = os.path.join(folder, "clip.mp4")
        os.makedirs(os.path.join(folder, "clip_frames"))
        for i in range(45):
            open(os.path.join(folder, "clip_frames", "f%02d.png" % i), "w").close()
        found = job(jobs.RENDERING, "Recording the camera move")
        found.context = {"shot": {"clip": clip, "frames": 90, "times": [0, 1, 2], "keys": os.path.join(folder, "k")}}
        c = chat(video="rendering")
        self.assertTrue(video_track.follow(c, Registry(found), now=1.0))
        self.assertEqual(c.video_progress, 48)  # 45 of 93 pictures


if __name__ == "__main__":
    unittest.main()
