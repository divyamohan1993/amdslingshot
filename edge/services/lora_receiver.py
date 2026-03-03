"""
JalNetra -- Async LoRa Receiver Daemon

Receives and parses binary LoRa packets from ESP32-S3 sensor nodes.
In VM/prototype mode, simulates realistic LoRa packet reception with:
  - Configurable number of concurrent sensor nodes (default 20)
  - Realistic sensor value generation with drift, noise, and anomalies
  - CRC-16 validation on every packet
  - Automatic node discovery and RSSI link-quality tracking
  - Asyncio-native packet queuing for downstream consumers

Packet format (32 bytes):
  Offset  Size  Field
  0       2     node_id       (uint16, big-endian)
  2       1     msg_type      (uint8: 0x01=reading, 0x02=heartbeat, 0x03=alert)
  3       2     tds           (uint16, raw ppm * 10)
  5       2     ph            (uint16, raw pH * 100)
  7       2     turbidity     (uint16, raw NTU * 100)
  9       2     flow          (uint16, raw L/min * 100)
  11      2     level         (uint16, raw cm)
  13      1     battery       (uint8, percentage 0-100)
  14      1     rssi          (int8, dBm as unsigned: rssi + 200)
  15      2     crc16         (CRC-CCITT over bytes 0..14)
  17      15    padding       (reserved, zeroed)
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

logger = logging.getLogger("jalnetra.lora_receiver")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACKET_SIZE = 32
HEADER_FMT = ">HB"  # node_id(2) + msg_type(1)
PAYLOAD_FMT = ">HHHHHBB"  # tds, ph, turbidity, flow, level, battery, rssi_enc
CRC_FMT = ">H"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
PAYLOAD_SIZE = struct.calcsize(PAYLOAD_FMT)
CRC_SIZE = struct.calcsize(CRC_FMT)
DATA_END = HEADER_SIZE + PAYLOAD_SIZE  # 15
CRC_END = DATA_END + CRC_SIZE  # 17


class MsgType(IntEnum):
    READING = 0x01
    HEARTBEAT = 0x02
    ALERT = 0x03


# ---------------------------------------------------------------------------
# CRC-16 CCITT (poly 0x1021, init 0xFFFF)
# ---------------------------------------------------------------------------

def _crc16_ccitt(data: bytes, *, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    """Compute CRC-16/CCITT over *data*."""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


# ---------------------------------------------------------------------------
# Parsed reading dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SensorReading:
    """A validated, parsed sensor reading from a single LoRa packet."""

    node_id: int
    msg_type: MsgType
    tds_ppm: float
    ph: float
    turbidity_ntu: float
    flow_lpm: float
    level_cm: int
    battery_pct: int
    rssi_dbm: int
    received_at: float  # monotonic timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "msg_type": self.msg_type.name,
            "tds_ppm": self.tds_ppm,
            "ph": self.ph,
            "turbidity_ntu": self.turbidity_ntu,
            "flow_lpm": self.flow_lpm,
            "level_cm": self.level_cm,
            "battery_pct": self.battery_pct,
            "rssi_dbm": self.rssi_dbm,
            "received_at": self.received_at,
        }


# ---------------------------------------------------------------------------
# Packet parser
# ---------------------------------------------------------------------------

class PacketParseError(Exception):
    """Raised when a LoRa packet fails validation."""


def parse_lora_packet(raw: bytes) -> SensorReading:
    """Parse and validate a 32-byte LoRa binary packet.

    Raises ``PacketParseError`` on CRC mismatch or structural issues.
    """
    if len(raw) != PACKET_SIZE:
        raise PacketParseError(
            f"Expected {PACKET_SIZE} bytes, got {len(raw)}"
        )

    # CRC validation over first DATA_END bytes
    data_bytes = raw[:DATA_END]
    (crc_received,) = struct.unpack_from(CRC_FMT, raw, DATA_END)
    crc_computed = _crc16_ccitt(data_bytes)
    if crc_received != crc_computed:
        raise PacketParseError(
            f"CRC mismatch: received 0x{crc_received:04X}, "
            f"computed 0x{crc_computed:04X}"
        )

    node_id, msg_type_raw = struct.unpack_from(HEADER_FMT, raw, 0)
    try:
        msg_type = MsgType(msg_type_raw)
    except ValueError:
        raise PacketParseError(f"Unknown msg_type: 0x{msg_type_raw:02X}")

    tds_raw, ph_raw, turb_raw, flow_raw, level, battery, rssi_enc = (
        struct.unpack_from(PAYLOAD_FMT, raw, HEADER_SIZE)
    )

    return SensorReading(
        node_id=node_id,
        msg_type=msg_type,
        tds_ppm=tds_raw / 10.0,
        ph=ph_raw / 100.0,
        turbidity_ntu=turb_raw / 100.0,
        flow_lpm=flow_raw / 100.0,
        level_cm=level,
        battery_pct=min(battery, 100),
        rssi_dbm=int(rssi_enc) - 200,
        received_at=time.monotonic(),
    )


# ---------------------------------------------------------------------------
# Simulated sensor node (for VM prototype)
# ---------------------------------------------------------------------------

@dataclass
class _SimulatedNode:
    """Internal state for a single simulated sensor node."""

    node_id: int
    # Base values (represent the "true" water source conditions)
    base_tds: float = 0.0
    base_ph: float = 0.0
    base_turbidity: float = 0.0
    base_flow: float = 0.0
    base_level: int = 0
    battery: int = 100
    rssi: int = -65
    # Drift accumulators
    _tds_drift: float = 0.0
    _ph_drift: float = 0.0
    _turb_drift: float = 0.0
    _tick: int = 0

    def __post_init__(self) -> None:
        # Assign realistic base values per node to model diverse water sources
        rng = random.Random(self.node_id)
        self.base_tds = rng.uniform(120, 650)       # ppm
        self.base_ph = rng.uniform(6.2, 8.8)        # pH
        self.base_turbidity = rng.uniform(0.2, 8.0)  # NTU
        self.base_flow = rng.uniform(2.0, 25.0)     # L/min
        self.base_level = rng.randint(50, 400)       # cm
        self.battery = rng.randint(40, 100)
        self.rssi = rng.randint(-95, -45)

    def generate_reading(self) -> bytes:
        """Generate a realistic 32-byte LoRa packet with drift and noise."""
        self._tick += 1

        # Slow drift (simulates gradual environmental change)
        self._tds_drift += random.gauss(0, 0.3)
        self._ph_drift += random.gauss(0, 0.005)
        self._turb_drift += random.gauss(0, 0.05)

        # Clamp drift
        self._tds_drift = max(-80, min(80, self._tds_drift))
        self._ph_drift = max(-0.4, min(0.4, self._ph_drift))
        self._turb_drift = max(-2.0, min(2.0, self._turb_drift))

        # Diurnal cycle (temperature affects TDS/pH)
        hour_frac = (time.time() % 86400) / 86400.0
        diurnal = math.sin(2 * math.pi * hour_frac)

        # Sensor noise
        tds = self.base_tds + self._tds_drift + diurnal * 15 + random.gauss(0, 5)
        ph = self.base_ph + self._ph_drift + diurnal * 0.1 + random.gauss(0, 0.02)
        turbidity = self.base_turbidity + self._turb_drift + abs(random.gauss(0, 0.3))
        flow = self.base_flow + random.gauss(0, 0.5)
        level = self.base_level + int(random.gauss(0, 2))

        # Occasional anomalies (~2% chance per reading)
        if random.random() < 0.02:
            anomaly_type = random.choice(["tds_spike", "ph_drop", "turb_spike"])
            if anomaly_type == "tds_spike":
                tds += random.uniform(300, 1500)
                logger.debug("Node %d: simulated TDS spike to %.1f", self.node_id, tds)
            elif anomaly_type == "ph_drop":
                ph -= random.uniform(1.5, 3.0)
                logger.debug("Node %d: simulated pH drop to %.2f", self.node_id, ph)
            elif anomaly_type == "turb_spike":
                turbidity += random.uniform(15, 50)
                logger.debug(
                    "Node %d: simulated turbidity spike to %.1f",
                    self.node_id,
                    turbidity,
                )

        # Battery drain (~0.1% per reading on average)
        if random.random() < 0.1:
            self.battery = max(0, self.battery - 1)

        # RSSI jitter
        rssi = self.rssi + random.randint(-5, 5)

        # Clamp to valid ranges
        tds = max(0, min(6553.5, tds))
        ph = max(0, min(14.0, ph))
        turbidity = max(0, min(655.35, turbidity))
        flow = max(0, min(655.35, flow))
        level = max(0, min(65535, level))
        rssi = max(-200, min(55, rssi))

        # Pack the binary packet
        tds_raw = int(round(tds * 10))
        ph_raw = int(round(ph * 100))
        turb_raw = int(round(turbidity * 100))
        flow_raw = int(round(flow * 100))
        level_raw = int(level)
        rssi_enc = rssi + 200

        header = struct.pack(HEADER_FMT, self.node_id, MsgType.READING)
        payload = struct.pack(
            PAYLOAD_FMT,
            tds_raw, ph_raw, turb_raw, flow_raw,
            level_raw, self.battery, rssi_enc,
        )
        data = header + payload
        crc = _crc16_ccitt(data)
        crc_bytes = struct.pack(CRC_FMT, crc)
        padding = b"\x00" * (PACKET_SIZE - len(data) - CRC_SIZE)

        return data + crc_bytes + padding


# ---------------------------------------------------------------------------
# Node discovery tracker
# ---------------------------------------------------------------------------

@dataclass
class NodeInfo:
    """Tracked metadata for a discovered sensor node."""

    node_id: int
    first_seen: float
    last_seen: float
    packet_count: int = 0
    crc_errors: int = 0
    rssi_samples: list[int] = field(default_factory=list)

    @property
    def avg_rssi(self) -> float:
        if not self.rssi_samples:
            return 0.0
        return sum(self.rssi_samples) / len(self.rssi_samples)

    @property
    def link_quality_pct(self) -> float:
        """Approximate link quality from average RSSI (0-100%)."""
        avg = self.avg_rssi
        if avg >= -50:
            return 100.0
        if avg <= -110:
            return 0.0
        return round((avg + 110) / 60 * 100, 1)

    def record_packet(self, rssi_dbm: int) -> None:
        self.last_seen = time.monotonic()
        self.packet_count += 1
        self.rssi_samples.append(rssi_dbm)
        # Keep last 100 RSSI samples for rolling average
        if len(self.rssi_samples) > 100:
            self.rssi_samples = self.rssi_samples[-100:]


# ---------------------------------------------------------------------------
# Async LoRa Receiver
# ---------------------------------------------------------------------------

class AsyncLoRaReceiver:
    """Async daemon that receives, parses, and queues LoRa sensor packets.

    In simulation mode (default for VM prototype), spawns background tasks
    that generate realistic sensor readings from ``num_nodes`` virtual nodes,
    each transmitting every ``packet_interval_sec`` seconds.

    Parsed readings are placed on an :class:`asyncio.Queue` for downstream
    consumers (model service, WebSocket broadcast, database writer).

    Usage::

        receiver = AsyncLoRaReceiver(num_nodes=20, packet_interval_sec=30)
        await receiver.start()  # begins background reception
        reading = await receiver.get_reading()  # blocks until next reading
        await receiver.stop()
    """

    def __init__(
        self,
        *,
        num_nodes: int = 20,
        packet_interval_sec: float = 30.0,
        queue_maxsize: int = 1000,
        simulate: bool = True,
    ) -> None:
        self._num_nodes = num_nodes
        self._packet_interval = packet_interval_sec
        self._simulate = simulate
        self._queue: asyncio.Queue[SensorReading] = asyncio.Queue(
            maxsize=queue_maxsize
        )
        self._nodes: dict[int, NodeInfo] = {}
        self._sim_nodes: list[_SimulatedNode] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._total_packets = 0
        self._total_crc_errors = 0

    # -- Public API ---------------------------------------------------------

    async def start(self) -> None:
        """Start the LoRa receiver daemon."""
        if self._running:
            logger.warning("LoRa receiver already running")
            return
        self._running = True
        logger.info(
            "Starting LoRa receiver: simulate=%s, nodes=%d, interval=%.1fs",
            self._simulate,
            self._num_nodes,
            self._packet_interval,
        )
        if self._simulate:
            self._sim_nodes = [
                _SimulatedNode(node_id=i + 1) for i in range(self._num_nodes)
            ]
            for sim_node in self._sim_nodes:
                task = asyncio.create_task(
                    self._simulation_loop(sim_node),
                    name=f"lora-sim-node-{sim_node.node_id}",
                )
                self._tasks.append(task)
            logger.info("Spawned %d simulated sensor node tasks", len(self._tasks))
        else:
            # Real hardware: serial port listener would go here
            task = asyncio.create_task(
                self._serial_listener(),
                name="lora-serial-listener",
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        """Gracefully stop the receiver and cancel all tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.error("Task error during shutdown: %s", result)
        self._tasks.clear()
        logger.info(
            "LoRa receiver stopped. Total packets: %d, CRC errors: %d",
            self._total_packets,
            self._total_crc_errors,
        )

    async def get_reading(self, timeout: float | None = None) -> SensorReading:
        """Get the next validated reading from the queue.

        Args:
            timeout: Maximum seconds to wait. ``None`` waits indefinitely.

        Raises:
            asyncio.TimeoutError: If timeout is exceeded.
        """
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    def get_reading_nowait(self) -> SensorReading | None:
        """Non-blocking read. Returns ``None`` if queue is empty."""
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @property
    def discovered_nodes(self) -> dict[int, NodeInfo]:
        """Return a snapshot of all discovered sensor nodes."""
        return dict(self._nodes)

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "total_packets": self._total_packets,
            "total_crc_errors": self._total_crc_errors,
            "discovered_nodes": len(self._nodes),
            "queue_size": self._queue.qsize(),
            "nodes": {
                nid: {
                    "packet_count": info.packet_count,
                    "crc_errors": info.crc_errors,
                    "avg_rssi": round(info.avg_rssi, 1),
                    "link_quality_pct": info.link_quality_pct,
                }
                for nid, info in self._nodes.items()
            },
        }

    # -- Internal: simulation -----------------------------------------------

    async def _simulation_loop(self, sim_node: _SimulatedNode) -> None:
        """Background task simulating periodic LoRa transmissions."""
        # Stagger start to avoid all nodes transmitting at once
        stagger = random.uniform(0, self._packet_interval)
        await asyncio.sleep(stagger)

        while self._running:
            try:
                raw_packet = sim_node.generate_reading()

                # Simulate occasional CRC corruption (~0.5% of packets)
                if random.random() < 0.005:
                    corrupted = bytearray(raw_packet)
                    idx = random.randint(0, DATA_END - 1)
                    corrupted[idx] ^= random.randint(1, 255)
                    raw_packet = bytes(corrupted)

                await self._process_raw_packet(raw_packet)

                # Realistic timing jitter (+/- 10%)
                jitter = self._packet_interval * random.uniform(-0.10, 0.10)
                await asyncio.sleep(self._packet_interval + jitter)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "Unexpected error in simulation loop for node %d",
                    sim_node.node_id,
                )
                await asyncio.sleep(1.0)

    # -- Internal: serial (placeholder for real hardware) --------------------

    async def _serial_listener(self) -> None:
        """Placeholder for real USB-serial LoRa receiver.

        In production, this reads from /dev/ttyUSB0 using aioserial
        or asyncio stream reader on the serial device file.
        """
        logger.info("Serial listener started (placeholder -- no hardware attached)")
        while self._running:
            await asyncio.sleep(5.0)

    # -- Internal: packet processing ----------------------------------------

    async def _process_raw_packet(self, raw: bytes) -> None:
        """Parse, validate, and enqueue a raw LoRa packet."""
        self._total_packets += 1

        try:
            reading = parse_lora_packet(raw)
        except PacketParseError as exc:
            self._total_crc_errors += 1
            logger.warning("Packet parse error (total CRC errors: %d): %s",
                           self._total_crc_errors, exc)
            return

        # Auto-discover / update node tracking
        now = time.monotonic()
        if reading.node_id not in self._nodes:
            self._nodes[reading.node_id] = NodeInfo(
                node_id=reading.node_id,
                first_seen=now,
                last_seen=now,
            )
            logger.info(
                "Discovered new sensor node: id=%d, RSSI=%d dBm",
                reading.node_id,
                reading.rssi_dbm,
            )
        self._nodes[reading.node_id].record_packet(reading.rssi_dbm)

        # Enqueue for downstream consumers
        try:
            self._queue.put_nowait(reading)
        except asyncio.QueueFull:
            # Drop oldest reading to make room
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(reading)
            logger.warning(
                "Reading queue full -- dropped oldest reading (node %d)",
                reading.node_id,
            )

        logger.debug(
            "Queued reading: node=%d TDS=%.1f pH=%.2f turb=%.2f RSSI=%d",
            reading.node_id,
            reading.tds_ppm,
            reading.ph,
            reading.turbidity_ntu,
            reading.rssi_dbm,
        )
