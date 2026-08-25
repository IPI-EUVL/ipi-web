from __future__ import annotations

import time

from chamber_ctl.subsystems import uuids
from ipi_ecs.dds import subsystem as dds_subsystem

from ipi_webview.dds.events import DataSource
from ipi_webview.dds.models import StatusSeverity
from ipi_webview.dds.transport import EcsDdsTransport


class FakeAwaiter:
    def __init__(self) -> None:
        self.success = None
        self.failure = None

    def then(self, callback):
        self.success = callback
        return self

    def catch(self, callback):
        self.failure = callback
        return self

    def resolve(self, value=None) -> None:
        assert self.success is not None
        self.success(value)

    def reject(self, *args, **kwargs) -> None:
        assert self.failure is not None
        self.failure(*args, **kwargs)


class FakeRemoteKv:
    def __init__(self) -> None:
        self.callback = None
        self.reads = []

    def on_new_data_received(self, callback) -> None:
        self.callback = callback

    def try_get(self):
        awaiter = FakeAwaiter()
        self.reads.append(awaiter)
        return awaiter


class FakeHandle:
    def __init__(self) -> None:
        self.remote_kvs = []
        self.system = []

    def add_remote_kv(self, target_uuid, descriptor):
        remote = FakeRemoteKv()
        self.remote_kvs.append((target_uuid, descriptor, remote))
        return remote

    def get_all(self):
        return self.system


class FakeInfo:
    def __init__(self, subsystem_uuid, name: str) -> None:
        self.subsystem_uuid = subsystem_uuid
        self.name = name

    def get_uuid(self):
        return self.subsystem_uuid

    def get_name(self):
        return self.name


class FakeRemoteSubsystem:
    def __init__(self, info: FakeInfo) -> None:
        self.info = info
        self.status_reads = []

    def get_info(self):
        return self.info

    def get_status(self):
        awaiter = FakeAwaiter()
        self.status_reads.append(awaiter)
        return awaiter


class FakeStatusItem:
    def get_severity(self):
        return dds_subsystem.StatusItem.STATE_WARN

    def get_code(self):
        return 12

    def get_message(self):
        return "Needs attention"


class FakeSubsystemState:
    def __init__(self, status_items=None):
        self.status_items = [] if status_items is None else status_items

    def get_status(self):
        return dds_subsystem.SubsystemStatus.STATE_ALIVE

    def get_status_items(self):
        return self.status_items


class FakeClient:
    def __init__(self, *_args, **_kwargs) -> None:
        self.ready = FakeAwaiter()
        self.handle = FakeHandle()
        self.registered = []
        self.closed = False

    def when_ready(self):
        return self.ready

    def register_subsystem(self, name, subsystem_uuid, temporary=False):
        self.registered.append((name, subsystem_uuid, temporary))
        return self.handle

    def close(self) -> None:
        self.closed = True


def test_transport_registers_only_locally_read_only_kvs() -> None:
    clients = []
    events = []

    def client_factory(*args, **kwargs):
        created = FakeClient(*args, **kwargs)
        clients.append(created)
        return created

    transport = EcsDdsTransport("127.0.0.1", events.append, client_factory=client_factory)
    transport.start()
    clients[0].ready.resolve()

    assert len(clients[0].registered) == 1
    assert clients[0].registered[0][2] is True
    assert {descriptor.get_key() for _, descriptor, _ in clients[0].handle.remote_kvs} == {
        b"experiment_state",
        b"experiment_reasons",
        b"cur_dose",
        b"cur_time",
        b"queue",
            b"state",
        b"position",
        b"status",
        b"sample",
    }
    assert all(descriptor.get_readable() for _, descriptor, _ in clients[0].handle.remote_kvs)
    assert not any(descriptor.get_writable() for _, descriptor, _ in clients[0].handle.remote_kvs)
    live_progress_targets = {
        target_uuid
        for target_uuid, descriptor, _ in clients[0].handle.remote_kvs
        if descriptor.get_key() in {b"cur_dose", b"cur_time"}
    }
    assert live_progress_targets == {uuids.UUID_EUV_ACQUISITION_CONTROLLER}
    assert any(event.source is DataSource.TRANSPORT and event.value is True for event in events)

    transport.close()
    assert clients[0].closed


def test_transport_fetches_fresh_known_subsystem_statuses() -> None:
    clients = []
    events = []

    def client_factory(*args, **kwargs):
        created = FakeClient(*args, **kwargs)
        clients.append(created)
        return created

    transport = EcsDdsTransport("127.0.0.1", events.append, client_factory=client_factory)
    transport.start()
    clients[0].ready.resolve()

    info = FakeInfo(uuids.UUID_EXPOSURE_CONTROLLER, "Live Exposure Controller")
    remote = FakeRemoteSubsystem(info)
    clients[0].handle.system = [(remote, FakeSubsystemState())]
    transport.poll_subsystems()
    assert len(remote.status_reads) == 1
    remote.status_reads[0].resolve(FakeSubsystemState([FakeStatusItem()]))

    subsystem_event = [event for event in events if event.source is DataSource.SUBSYSTEMS][-1]
    exposure = next(row for row in subsystem_event.value if row.uuid == uuids.UUID_EXPOSURE_CONTROLLER)
    queue = next(row for row in subsystem_event.value if row.uuid == uuids.UUID_EXPERIMENT_QUEUE_CONTROLLER)

    assert exposure.name == "Live Exposure Controller"
    assert exposure.connected is True
    assert exposure.status_items[0].severity is StatusSeverity.WARNING
    assert exposure.status_items[0].code == 12
    assert exposure.status_items[0].message == "Needs attention"
    assert queue.connected is False

    transport.close()


def test_transport_retries_after_a_subsystem_status_read_times_out() -> None:
    clients = []
    events = []

    def client_factory(*args, **kwargs):
        created = FakeClient(*args, **kwargs)
        clients.append(created)
        return created

    transport = EcsDdsTransport(
        "127.0.0.1",
        events.append,
        client_factory=client_factory,
        subsystem_poll_timeout=0.01,
    )
    transport.start()
    clients[0].ready.resolve()

    info = FakeInfo(uuids.UUID_OSCILLOSCOPE_CONTROLLER, "Oscilloscope Controller")
    remote = FakeRemoteSubsystem(info)
    clients[0].handle.system = [(remote, FakeSubsystemState())]
    transport.poll_subsystems()
    time.sleep(0.03)

    latest = [event for event in events if event.source is DataSource.SUBSYSTEMS][-1]
    assert latest.value is None
    assert "Oscilloscope Controller" in latest.error

    transport.poll_subsystems()
    assert len(remote.status_reads) == 2
    remote.status_reads[1].resolve(FakeSubsystemState([FakeStatusItem()]))
    latest = [event for event in events if event.source is DataSource.SUBSYSTEMS][-1]
    scope = next(row for row in latest.value if row.uuid == uuids.UUID_OSCILLOSCOPE_CONTROLLER)
    assert scope.connected is True
    assert scope.status_items[0].message == "Needs attention"

    transport.close()


def test_transport_repolls_existing_stage_handles_after_reconnect() -> None:
    clients = []
    events = []

    def client_factory(*args, **kwargs):
        created = FakeClient(*args, **kwargs)
        clients.append(created)
        return created

    transport = EcsDdsTransport("127.0.0.1", events.append, client_factory=client_factory)
    transport.start()
    clients[0].ready.resolve()

    stage_status = next(
        remote
        for _, descriptor, remote in clients[0].handle.remote_kvs
        if descriptor.get_key() == b"status"
    )
    assert len(stage_status.reads) == 1

    clients[0].ready.resolve()

    assert len(clients[0].handle.remote_kvs) == 9
    assert len(stage_status.reads) == 2
    stage_status.reads[0].resolve(dds_subsystem.SubsystemStatus.STATE_DISCONNECTED)
    stage_status.reads[1].resolve(0)
    stage_events = [event for event in events if event.source is DataSource.STAGE_STATE]
    assert [event.value.name for event in stage_events] == ["IDLE"]

    transport.close()