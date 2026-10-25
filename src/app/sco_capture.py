"""Bounded raw SCO sink for a future Bumble ScoLink; no controller access.

Payload is deliberately NOT labeled PCM: controller coding/routing must first
be verified on hardware. This module never starts Bluetooth or changes services.
"""
import json
import time
from pathlib import Path

class ScoCapture:
    def __init__(self, directory, max_bytes=320000):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.payload=(self.directory/'sco.raw').open('wb')
        self.index=(self.directory/'packets.jsonl').open('w',encoding='utf-8')
        self.max_bytes=max_bytes
        self.bytes=0
        self.packets=0
        self.closed=False

    def __call__(self, packet):
        if self.closed:
            return
        data=bytes(packet.data)
        if len(data)!=packet.data_total_length:
            raise ValueError('SCO payload length mismatch')
        if self.bytes+len(data)>self.max_bytes:
            self.close('size-limit')
            return
        self.index.write(json.dumps({'monotonic_ns':time.monotonic_ns(),
          'handle':packet.connection_handle,'status':int(packet.packet_status),
          'offset':self.bytes,'length':len(data)})+'\n')
        self.payload.write(data)
        self.bytes+=len(data)
        self.packets+=1

    def close(self, reason='completed'):
        if self.closed:
            return
        self.closed=True
        self.payload.close()
        self.index.close()
        (self.directory/'manifest.json').write_text(json.dumps({
          'format':'raw HCI SCO payload; encoding NOT yet verified',
          'bytes':self.bytes,'packets':self.packets,'stop_reason':reason},indent=2))
