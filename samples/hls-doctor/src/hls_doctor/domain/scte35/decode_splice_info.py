"""Decode a base64 or hex SCTE-35 splice_info_section (spec §13).

Only the structures ad diagnosis needs are interpreted; unknown descriptors
are preserved as raw hex, mirroring how unknown playlist tags are handled.
"""

import base64
import binascii

from hls_doctor.domain.scte35.read_bits import BitReader
from hls_doctor.domain.scte35.splice_model import (
    SEGMENTATION_TYPE_NAMES,
    SPLICE_COMMAND_NAMES,
    SegmentationDescriptor,
    SpliceInfoSection,
    SpliceInsert,
)
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

PTS_CLOCK_HZ = 90_000
TABLE_ID = 0xFC


def decode_payload_text(payload: str) -> bytes:
    text = payload.strip()
    if text.lower().startswith("0x"):
        return bytes.fromhex(text[2:])
    try:
        return base64.b64decode(text, validate=True)
    except binascii.Error:
        try:
            return bytes.fromhex(text)
        except ValueError as error:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                "The SCTE-35 payload is neither valid base64 nor hex.",
                "Pass the cue payload exactly as it appears in the playlist.",
            ) from error


def decode_splice_info(payload: str) -> SpliceInfoSection:
    reader = BitReader(decode_payload_text(payload))
    try:
        return read_section(reader)
    except ValueError as error:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"The SCTE-35 payload is truncated or malformed: {error}.",
            "Check that the cue attribute carries the complete payload.",
        ) from error


def read_section(reader: BitReader) -> SpliceInfoSection:
    table_id = reader.read(8)
    if table_id != TABLE_ID:
        raise ValueError(f"table_id 0x{table_id:02x} is not a splice_info_section")
    reader.read(1 + 1 + 2 + 12)  # section_syntax, private, sap, section_length
    reader.read(8)  # protocol_version
    encrypted = reader.read_flag()
    reader.read(6)  # encryption_algorithm
    pts_adjustment = reader.read(33)
    reader.read(8 + 12)  # cw_index, tier
    command_length = reader.read(12)
    command_type = reader.read(8)
    section = SpliceInfoSection(
        command_type=command_type,
        command_name=SPLICE_COMMAND_NAMES.get(command_type, f"unknown_0x{command_type:02x}"),
        pts_adjustment_seconds=pts_adjustment / PTS_CLOCK_HZ,
    )
    if encrypted:
        return section  # encrypted payloads are reported, not decoded
    command_end = reader.position + command_length * 8
    if command_type == 0x05:
        section.splice_insert = read_splice_insert(reader)
    elif command_type == 0x06:
        section.time_signal_pts_seconds = read_splice_time(reader)
    if 0 <= command_end <= len(reader.data) * 8:
        reader.position = max(reader.position, command_end)
    read_descriptors(reader, section)
    return section


def read_splice_insert(reader: BitReader) -> SpliceInsert:
    event_id = reader.read(32)
    cancel = reader.read_flag()
    reader.read(7)
    insert = SpliceInsert(event_id=event_id, cancel=cancel)
    if cancel:
        return insert
    insert.out_of_network = reader.read_flag()
    program_splice = reader.read_flag()
    duration_flag = reader.read_flag()
    insert.splice_immediate = reader.read_flag()
    reader.read(4)
    if program_splice and not insert.splice_immediate:
        insert.splice_pts_seconds = read_splice_time(reader)
    if duration_flag:
        insert.auto_return = reader.read_flag()
        reader.read(6)
        insert.break_duration_seconds = reader.read(33) / PTS_CLOCK_HZ
    insert.unique_program_id = reader.read(16)
    insert.avail_num = reader.read(8)
    insert.avails_expected = reader.read(8)
    return insert


def read_splice_time(reader: BitReader) -> float | None:
    if not reader.read_flag():
        return None
    reader.read(6)
    return reader.read(33) / PTS_CLOCK_HZ


def read_descriptors(reader: BitReader, section: SpliceInfoSection) -> None:
    if reader.remaining_bits < 16:
        return
    loop_length = reader.read(16)
    end = reader.position + loop_length * 8
    while reader.position + 16 <= min(end, len(reader.data) * 8 - 32):
        tag = reader.read(8)
        length = reader.read(8)
        body = reader.read_bytes(length)
        if tag == 0x02:
            section.segmentation_descriptors.append(read_segmentation(body))
        else:
            section.unknown_descriptors_hex.append(f"{tag:02x}:{body.hex()}")


def read_segmentation(body: bytes) -> SegmentationDescriptor:
    reader = BitReader(body)
    reader.read(32)  # identifier "CUEI"
    descriptor = SegmentationDescriptor(event_id=reader.read(32), cancel=reader.read_flag())
    reader.read(7)
    if descriptor.cancel:
        return descriptor
    reader.read_flag()  # program_segmentation
    duration_flag = reader.read_flag()
    reader.read_flag()  # delivery_not_restricted
    reader.read(5)  # restriction bits or reserved
    if duration_flag:
        descriptor.duration_seconds = reader.read(40) / 90_000
    descriptor.upid_type = reader.read(8)
    upid_length = reader.read(8)
    descriptor.upid_hex = reader.read_bytes(upid_length).hex() or None
    descriptor.type_id = reader.read(8)
    descriptor.type_name = SEGMENTATION_TYPE_NAMES.get(descriptor.type_id)
    descriptor.segment_num = reader.read(8)
    descriptor.segments_expected = reader.read(8)
    return descriptor
