"""A minimal big-endian bit reader for SCTE-35 binary payloads."""


class BitReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0  # in bits

    @property
    def remaining_bits(self) -> int:
        return len(self.data) * 8 - self.position

    def read(self, bit_count: int) -> int:
        """Read an unsigned big-endian integer of `bit_count` bits."""
        if bit_count > self.remaining_bits:
            raise ValueError(f"needed {bit_count} bits but only {self.remaining_bits} remain")
        value = 0
        for _ in range(bit_count):
            byte = self.data[self.position // 8]
            bit = (byte >> (7 - self.position % 8)) & 1
            value = (value << 1) | bit
            self.position += 1
        return value

    def read_flag(self) -> bool:
        return self.read(1) == 1

    def read_bytes(self, byte_count: int) -> bytes:
        if self.position % 8 != 0:
            raise ValueError("byte read is not aligned")
        start = self.position // 8
        if start + byte_count > len(self.data):
            raise ValueError("byte read past the end of the payload")
        self.position += byte_count * 8
        return self.data[start : start + byte_count]
