from __future__ import annotations

import json
import uuid

import segment_bytes

from chamber_ctl.subsystems.exposure_controller import ExposureSettings
from ipi_ecs.subsystems.experiment_controller import RunState

from ipi_webview.dds.codecs import (
    decode_batch_controller_state,
    decode_experiment_reasons,
    decode_experiment_state,
    decode_queue,
)
from ipi_webview.dds.models import ExperimentPhase


def _settings(*, name: str = "Batch A", sample: str = "2") -> ExposureSettings:
    settings = ExposureSettings()
    settings.data = {
        "name": name,
        "description": "Test exposure",
        "target_time": 0.0,
        "target_dose": 4.5,
        "operator": "Operator",
        "zr_filter": "ZR-1",
        "sample": sample,
        "sample_type": "resist",
        "base_pressure": 1.0,
        "operating_pressure": 2.0,
        "flow_sccm": 3.0,
    }
    return settings


def test_decode_active_experiment_state() -> None:
    run_uuid = uuid.uuid4()
    run = RunState("exposure", _settings(), s_uuid=run_uuid)
    payload = segment_bytes.encode(
        [
            ExperimentPhase.RUNNING.to_bytes(1, byteorder="big"),
            run.encode().encode("utf-8"),
        ]
    )

    state = decode_experiment_state(payload)

    assert state.phase is ExperimentPhase.RUNNING
    assert state.run is not None
    assert state.run.uuid == run_uuid
    assert state.run.name == "Batch A"
    assert state.run.settings.sample_slot == 2
    assert state.run.settings.target_dose == 4.5


def test_decode_stopped_state_has_no_run() -> None:
    payload = segment_bytes.encode([ExperimentPhase.STOPPED.to_bytes(1, byteorder="big"), b""])

    state = decode_experiment_state(payload)

    assert state.phase is ExperimentPhase.STOPPED
    assert state.run is None


def test_decode_experiment_reasons() -> None:
    payload = segment_bytes.encode(
        [
            segment_bytes.encode([b"Laser Controller", b"Ongoing", b"Warming up"]),
            segment_bytes.encode([b"Target Controller", b"Done", b""]),
        ]
    )

    reasons = decode_experiment_reasons(payload)

    assert [(reason.subsystem, reason.status, reason.reason) for reason in reasons] == [
        ("Laser Controller", "Ongoing", "Warming up"),
        ("Target Controller", "Done", ""),
    ]


def test_decode_queue_preserves_malformed_item_position() -> None:
    payload = segment_bytes.encode(
        [
            _settings(name="Batch A", sample="0").encode().encode("utf-8"),
            b"not-json",
            _settings(name="Batch B", sample="3").encode().encode("utf-8"),
        ]
    )

    queue = decode_queue(payload)

    assert len(queue) == 3
    assert queue[0].position == 0
    assert queue[0].settings is not None
    assert queue[0].settings.name == "Batch A"
    assert queue[1].position == 1
    assert queue[1].settings is None
    assert queue[1].error is not None
    assert queue[2].position == 2
    assert queue[2].settings is not None
    assert queue[2].settings.sample_slot == 3


def test_decode_batch_controller_state_preserves_plan_order_and_attempts() -> None:
    batch_uuid = uuid.uuid4()
    run_uuid = uuid.uuid4()
    payload = json.dumps(
        {
            "schema_version": 1,
            "emitted_at": 100.0,
            "phase": "waiting_continue",
            "message": "Operator Continue is required.",
            "last_error": None,
            "lease_owned": True,
            "active_batch_uuid": str(batch_uuid),
            "active_manifest": {
                "schema_version": 1,
                "batch_uuid": str(batch_uuid),
                "revision": 2,
                "status": "active",
                "mode": "manual",
                "plan": {
                    "schema_version": 1,
                    "template": {
                        "name": "Contrast A",
                        "description": "Ordered curve",
                        "operator": "Operator",
                        "zr_filter": "ZR-1",
                        "sample_type": "resist",
                        "base_pressure": 1.0,
                        "operating_pressure": 2.0,
                        "flow_sccm": 3.0,
                    },
                    "entries": [
                        {"sample": 4, "mode": "dose", "target": 10.0},
                        {"sample": 1, "mode": "dose", "target": 20.0},
                    ],
                },
                "created_at": 90.0,
                "updated_at": 99.0,
                "origin": "tk_gui",
                "submitted_by": "",
                "paused": False,
                "cancel_pending": False,
                "acknowledged_runs": [],
                "revision_note": "Curve",
            },
            "assessment": {
                "decision": {
                    "kind": "start_remainder",
                    "message": "Sample 5 needs 10 dose.",
                    "run_uuid": None,
                    "sample": 4,
                    "sample_number": 5,
                    "settings": None,
                },
                "progress": [
                    {
                        "sample": 4,
                        "sample_number": 5,
                        "mode": "dose",
                        "target": 10.0,
                        "tolerance": 1.0,
                        "cumulative_dose": 0.0,
                        "cumulative_runtime": 0.0,
                        "attempt_count": 0,
                        "state": "under_target",
                        "remainder": 10.0,
                        "overshoot": 0.0,
                    }
                ],
            },
            "attempts": [
                {
                    "run_uuid": str(run_uuid),
                    "sample": 4,
                    "sample_number": 5,
                    "created_at": 95.0,
                    "end_time": 96.0,
                    "status": "STOPPED",
                    "end_reason": "done",
                    "dose": 5.0,
                    "runtime": 2.0,
                    "snapshot_count": 1,
                    "validation_error": None,
                }
            ],
            "manifests": [],
        }
    ).encode("utf-8")

    state = decode_batch_controller_state(payload)

    assert state.active_batch_uuid == batch_uuid
    assert state.mode == "manual"
    assert [(entry.order, entry.sample_slot, entry.target) for entry in state.plan_entries] == [
        (1, 4, 10.0),
        (2, 1, 20.0),
    ]
    assert state.attempts[0].run_uuid == run_uuid


def test_decode_batch_controller_state_prefers_global_execution_mode() -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "emitted_at": 100.0,
            "phase": "waiting_continue",
            "message": "Manual mode is ready.",
            "last_error": None,
            "lease_owned": True,
            "execution_mode": "automatic",
            "active_batch_uuid": None,
            "active_manifest": None,
            "display_manifest": {
                "schema_version": 1,
                "batch_uuid": str(uuid.uuid4()),
                "revision": 1,
                "status": "draft",
                "mode": "manual",
                "plan": {"schema_version": 1, "template": {"name": "", "description": "", "operator": "", "zr_filter": "", "sample_type": "", "base_pressure": 0.0, "operating_pressure": 0.0, "flow_sccm": 0.0}, "entries": []},
                "created_at": 90.0,
                "updated_at": 99.0,
                "origin": "tk_gui",
                "submitted_by": "",
                "paused": True,
                "cancel_pending": False,
                "acknowledged_runs": [],
                "revision_note": "Created",
            },
            "assessment": None,
            "attempts": [],
            "manifests": [],
        }
    ).encode("utf-8")

    state = decode_batch_controller_state(payload)

    assert state.mode == "automatic"


def test_decode_completed_batch_uses_display_manifest_for_targets() -> None:
    batch_uuid = uuid.uuid4()
    payload = json.dumps(
        {
            "schema_version": 1,
            "emitted_at": 100.0,
            "phase": "completed",
            "message": "Every sample met its target.",
            "last_error": None,
            "lease_owned": False,
            "active_batch_uuid": None,
            "active_manifest": None,
            "display_manifest": {
                "schema_version": 1,
                "batch_uuid": str(batch_uuid),
                "revision": 2,
                "status": "completed",
                "mode": "manual",
                "plan": {
                    "schema_version": 1,
                    "template": {
                        "name": "Completed curve",
                        "description": "",
                        "operator": "Operator",
                        "zr_filter": "ZR-1",
                        "sample_type": "resist",
                        "base_pressure": 1.0,
                        "operating_pressure": 2.0,
                        "flow_sccm": 3.0,
                    },
                    "entries": [{"sample": 2, "mode": "dose", "target": 10.0}],
                },
                "created_at": 90.0,
                "updated_at": 99.0,
                "origin": "tk_gui",
                "submitted_by": "",
                "paused": True,
                "cancel_pending": False,
                "acknowledged_runs": [],
                "revision_note": "Completed",
            },
            "assessment": {
                "decision": {"kind": "complete", "message": "Every sample met its target."},
                "progress": [
                    {
                        "sample": 2,
                        "mode": "dose",
                        "target": 10.0,
                        "cumulative_dose": 12.0,
                        "cumulative_runtime": 4.0,
                        "attempt_count": 1,
                        "state": "overshot",
                        "remainder": 0.0,
                        "overshoot": 2.0,
                    }
                ],
            },
            "attempts": [],
            "manifests": [],
        }
    ).encode("utf-8")

    state = decode_batch_controller_state(payload)

    assert state.active_batch_uuid is None
    assert state.name == "Completed curve"
    assert state.manifest_status == "completed"
    assert [(entry.sample_slot, entry.target, entry.state) for entry in state.plan_entries] == [(2, 10.0, "overshot")]