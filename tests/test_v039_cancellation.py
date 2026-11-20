"""Regression tests with a real loopback HTTP server; no Tiiny inference."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
with contextlib.redirect_stdout(io.StringIO()):
    spec = importlib.util.spec_from_file_location("v039_profiles", HERE / "test_v030_profiles.py")
    profile = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = profile
    spec.loader.exec_module(profile)
addon = profile.addon


class Device:
    """Controlled transport: a request can stall while Blender remains responsive."""
    def __init__(self, mode="poll", remote_stop=True):
        self.mode = mode
        self.remote_stop = remote_stop
        self.release = threading.Event()
        self.blocked = threading.Event()
        self.cancelled = threading.Event()
        self.posts = 0
        self.polls = 0
        self.handlers_finished = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, body, status=200):
                raw = json.dumps({"data": body}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                path = urlsplit(self.path).path
                if path.endswith("/cancel"):
                    owner.cancelled.set()
                    if owner.remote_stop:
                        self.reply({"status": "cancelled"})
                    else:
                        self.close_connection = True
                    return
                assert path == "/v1/3d/tasks", path
                owner.posts += 1
                if owner.mode == "submit":
                    owner.blocked.set()
                    owner.release.wait(5)
                self.reply({"task_id": "device-task"})

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/v1/3d/capabilities":
                    if owner.mode == "capabilities":
                        self.close_connection = True
                    else:
                        self.reply(profile.TRELLIS_CAPS)
                    return
                if "/artifacts/" in path:
                    owner.blocked.set()
                    owner.release.wait(5)
                    raw = profile.SHAPE_GLB
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    try:
                        self.wfile.write(raw)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    owner.handlers_finished.set()
                    return
                assert path == "/v1/3d/tasks/device-task", path
                owner.polls += 1
                if owner.mode == "poll" and owner.polls == 1:
                    self.reply({"status": "running", "progress": 50,
                                "message": "Shape diffusion 12/24"})
                    return
                if owner.mode == "poll":
                    owner.blocked.set()
                    owner.release.wait(5)
                if owner.mode == "outage":
                    if owner.polls == 1:
                        self.reply({"status": "running", "progress": 30})
                    else:
                        self.reply({}, status=503)
                    return
                if owner.mode == "responding" and owner.polls < 15:
                    self.reply({"status": "running", "progress": 0})
                    return
                artifact = {"artifact_type": "shape_preview", "artifact_id": "preview",
                            "payload_key": "glb"}
                output = {"artifacts": [artifact]}
                if owner.mode != "download":
                    output["glb"] = base64.b64encode(profile.SHAPE_GLB).decode()
                self.reply({"status": "completed", "progress": 100,
                            "result": {"output": output}})
                owner.handlers_finished.set()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(1)


def wait_for(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.01)
    return bool(predicate())


class CancellationContracts(unittest.TestCase):
    def setUp(self):
        self.initial_threads = set(threading.enumerate())
        self.temp = tempfile.TemporaryDirectory(prefix="tiiny-network-")
        self.root = Path(self.temp.name)
        self.source = self.root / "input.png"
        self.source.write_bytes(b"transport test image")
        addon._JOBS.clear()
        addon._JOB_CANCEL_EVENTS.clear()
        addon._JOB_REPORTS.clear()
        addon._REMOTE_CANCEL_TASKS.clear()
        while not addon._PENDING_IMPORT.empty():
            addon._PENDING_IMPORT.get_nowait()
        self.old_poll = addon._POLL_INTERVAL
        addon._POLL_INTERVAL = .01
        self.device = None
        self.worker = None

    def tearDown(self):
        try:
            if self.device:
                self.device.release.set()
            if self.worker and self.worker.is_alive():
                addon._cancel_all_jobs()
            if self.device:
                self.device.close()
            self.join_case_threads()
        finally:
            addon._POLL_INTERVAL = self.old_poll
        self.temp.cleanup()

    def join_case_threads(self):
        # Generation can finish before cancellation/report writers do. Wait for
        # all case-owned threads before deleting their report directory or
        # resetting shared addon state in the next case. Re-scan because a late
        # request may itself start a cancellation worker.
        deadline = time.monotonic() + 7
        while True:
            pending = [thread for thread in threading.enumerate()
                       if thread not in self.initial_threads]
            if not pending:
                return
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, "Background test threads did not finish: " +
                               ", ".join(thread.name for thread in pending))
            for thread in pending:
                # enumerate() can include a thread still inside Thread.start;
                # its parent is joined too, and the next scan will see it ready.
                if thread.ident is not None:
                    thread.join(max(0, deadline - time.monotonic()))

    def start(self, mode="poll", remote_stop=True, **changes):
        self.device = Device(mode, remote_stop)
        config = profile.settings(base=self.device.base, key="secret-network-key",
                                  image=str(self.source), output_dir=str(self.root / "results"),
                                  texture=False, allow_trellis_1024=False, **changes)
        self.jid = "network-" + mode
        addon._JOBS[self.jid] = {"state": "queued", "progress": 0}
        self.worker = threading.Thread(target=addon._generate_worker, args=(self.jid, config),
                                       daemon=True)
        self.worker.start()
        return config

    def report(self):
        files = list((self.root / "results").glob("*.json"))
        self.assertEqual(len(files), 1)
        raw = files[0].read_text()
        self.assertNotIn("secret-network-key", raw)
        self.assertNotIn(self.device.base, raw)
        return json.loads(raw)

    def stop(self):
        ctx = types.SimpleNamespace(scene=types.SimpleNamespace(
            tiiny_settings=types.SimpleNamespace(job_id=self.jid)))
        operator = types.SimpleNamespace(report=lambda *args: None)
        started = time.monotonic()
        self.assertEqual(addon.TIINY_OT_Cancel.execute(operator, ctx), {"FINISHED"})
        self.assertLess(time.monotonic() - started, .25)
        self.assertEqual(addon._job_get(self.jid)["state"], "cancelled")
        self.worker.join(.75)
        self.assertFalse(self.worker.is_alive(), "worker still waiting on blocked HTTP")
        self.assertTrue(addon._PENDING_IMPORT.empty())

    def test_stop_during_blocked_poll_is_immediate_and_journal_is_live(self):
        self.start()
        self.assertTrue(self.device.blocked.wait(2))
        before = self.report()
        self.assertEqual(before["stage_diagnostics"][0]["task_id"], "device-task")
        self.assertEqual(before["stage_diagnostics"][0]["last_server_progress"], 50)
        self.stop()
        self.assertTrue(self.device.cancelled.wait(1))
        self.assertTrue(wait_for(lambda: addon._job_get(self.jid).get("remote_cancel") == "confirmed"))
        self.device.release.set()
        self.assertTrue(self.device.handlers_finished.wait(1))
        self.assertEqual(self.device.posts, 1)
        self.assertEqual(self.report()["status"], "cancelled")
        self.assertTrue(addon._PENDING_IMPORT.empty())
        self.assertEqual(addon._job_get(self.jid)["state"], "cancelled")

    def test_offline_remote_stop_does_not_prevent_local_stop(self):
        self.start(remote_stop=False)
        self.assertTrue(self.device.blocked.wait(2))
        self.stop()
        self.assertTrue(wait_for(lambda: addon._job_get(self.jid).get("remote_cancel") == "unconfirmed"))
        self.assertEqual(self.report()["cancellation"]["remote_cancel"], "unconfirmed")

    def test_late_submission_response_is_cancelled_without_a_second_submission(self):
        config = self.start(mode="submit")
        self.assertTrue(self.device.blocked.wait(2))
        self.stop()
        self.assertTrue(addon._job_get(self.jid)["submission_pending"])
        with self.assertRaisesRegex(RuntimeError, 'earlier submission'):
            addon._begin_job(config)
        self.device.release.set()
        self.assertTrue(self.device.cancelled.wait(2))
        self.assertTrue(wait_for(lambda: not addon._job_get(self.jid).get("submission_pending")))
        self.assertEqual(self.device.posts, 1)
        self.assertEqual(self.device.polls, 0)
        self.assertTrue(addon._PENDING_IMPORT.empty())

    def test_stop_during_artifact_download_discards_late_result(self):
        self.start(mode="download")
        self.assertTrue(self.device.blocked.wait(2))
        self.stop()
        self.device.release.set()
        self.assertTrue(self.device.handlers_finished.wait(1))
        self.assertFalse(list((self.root / "results").glob("*.glb")))
        self.assertTrue(addon._PENDING_IMPORT.empty())

    def test_outage_deadline_is_bounded_and_does_not_repeat_post(self):
        self.start(mode="outage", network_grace_seconds=.12)
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(addon._job_get(self.jid)["state"], "failed")
        self.assertEqual(self.device.posts, 1)
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertGreater(report["stage_diagnostics"][0]["transient_poll_failures"], 0)
        self.assertEqual(report["stage_diagnostics"][0]["last_server_progress"], 30)
        self.assertIn("Local waiting stopped", report["error"])

    def test_responding_long_task_is_not_timed_out_for_unchanged_progress(self):
        self.start(mode="responding", network_grace_seconds=.05)
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())
        self.assertGreater(self.device.polls, 10)
        self.assertEqual(addon._job_get(self.jid)["state"], "importing")
        self.assertEqual(self.report()["status"], "saved")

    def test_capability_failure_still_leaves_a_report(self):
        self.start(mode="capabilities")
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failure_stage"], "capabilities")
        self.assertEqual(self.device.posts, 0)

    def test_admission_failure_does_not_leave_false_inflight_submission(self):
        self.jid = "admission"
        addon._JOBS[self.jid] = {"state": "running"}
        with mock.patch.object(addon, "_NETWORK_SLOTS") as slots:
            slots.acquire.return_value = False
            with self.assertRaises(RuntimeError):
                addon._job_request(self.jid, "POST", "http://example.test", "key",
                                   "/v1/3d/tasks", fields={"stage": "shape"})
        self.assertFalse(addon._job_get(self.jid)["submission_pending"])
        addon._JOB_CANCEL_EVENTS[self.jid] = threading.Event()
        addon._JOB_CANCEL_EVENTS[self.jid].set()
        with self.assertRaises(InterruptedError):
            addon._job_request(self.jid, "POST", "http://example.test", "key",
                               "/v1/3d/tasks", fields={"stage": "shape"})
        self.assertFalse(addon._job_get(self.jid)["submission_pending"])

    def test_cancelled_queue_entry_is_never_imported(self):
        jid = "queued-import"
        addon._JOBS[jid] = {"state": "importing", "stage": "import"}
        addon._PENDING_IMPORT.put((jid, "must-not-import.glb"))
        addon._stop_job(jid)
        with mock.patch.object(addon, "_ACTIVE", True), \
                mock.patch.object(addon, "_tools_enabled", return_value=False):
            addon._main_tick()
        self.assertTrue(addon._PENDING_IMPORT.empty())
        self.assertEqual(addon._job_get(jid)["state"], "cancelled")

    def test_scene_change_keeps_the_active_job_accessible(self):
        addon._JOBS["old-scene"] = {"state": "running", "stage": "shape"}
        ctx = types.SimpleNamespace(scene=types.SimpleNamespace(
            tiiny_settings=types.SimpleNamespace(job_id="")))
        self.assertEqual(addon._context_job_id(ctx), "old-scene")
        addon._cancel_all_jobs()
        self.assertEqual(addon._job_get("old-scene")["state"], "cancelled")

    def test_new_job_can_start_after_cancelled_poll_worker_exits(self):
        config = self.start()
        self.assertTrue(self.device.blocked.wait(2))
        self.stop()
        with mock.patch.object(addon, '_generate_worker') as run_new:
            new_id = addon._begin_job(config)
            self.assertNotEqual(new_id, self.jid)
            self.assertTrue(wait_for(lambda: run_new.called))
            self.assertFalse(addon._cancel_event(new_id).is_set())
        self.assertEqual(addon._job_get(self.jid)['state'], 'cancelled')

    def test_wall_deadline_then_late_post_cancels_and_releases_slots(self):
        jid = 'deadline-post'
        addon._JOBS[jid] = {'state': 'running'}
        release = threading.Event()
        remote_cancel = threading.Event()
        original = addon._bounded_call

        def delayed_request(method, base, key, path, **kwargs):
            if path.endswith('/cancel'):
                remote_cancel.set()
                return {'status': 'cancelled'}
            release.wait(2)
            return {'task_id': 'late-task'}

        def short_call(function, timeout, **kwargs):
            return original(function, min(timeout, .08), **kwargs)

        try:
            with mock.patch.object(addon, '_request', delayed_request), \
                    mock.patch.object(addon, '_bounded_call', short_call):
                with self.assertRaisesRegex(RuntimeError, 'deadline'):
                    addon._job_request(jid, 'POST', 'http://example.test', 'key',
                                       '/v1/3d/tasks', fields={'stage': 'shape'})
                self.assertTrue(addon._job_get(jid)['submission_pending'])
                release.set()
                self.assertTrue(remote_cancel.wait(1))
                self.assertTrue(wait_for(lambda: addon._job_get(jid).get('remote_cancel') == 'confirmed'))
        finally:
            release.set()
        acquired = []
        try:
            for _ in range(4):
                acquired.append(addon._NETWORK_SLOTS.acquire(timeout=1))
            self.assertTrue(all(acquired), 'abandoned request leaked a network slot')
        finally:
            for ok in acquired:
                if ok:
                    addon._NETWORK_SLOTS.release()


if __name__ == "__main__":
    unittest.main(verbosity=2)
