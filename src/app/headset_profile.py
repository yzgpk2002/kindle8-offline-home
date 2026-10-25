"""Cache only a verified RFCOMM channel for the explicitly selected headset."""
import json
from pathlib import Path

class ChannelCache:
    def __init__(self,path):self.path=Path(path)
    def get(self,target):
        try:
            if self.path.stat().st_size>1024:return None
            data=json.loads(self.path.read_text());channel=data.get('channel')
            if data.get('version')==1 and data.get('target')==target and type(channel) is int and 1<=channel<=30:return channel
        except (OSError,ValueError,TypeError,AttributeError):pass
        return None
    def save(self,target,channel):
        if type(channel) is not int or not 1<=channel<=30:raise ValueError('Invalid RFCOMM channel')
        tmp=self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version':1,'target':target,'channel':channel}));tmp.replace(self.path)
    def clear(self,target):
        if self.get(target) is not None:self.path.unlink(missing_ok=True)

async def open_channel(target,cache,open_dlc,discover):
    channel=cache.get(target)
    if channel is not None:
        try:return await open_dlc(channel),channel,True
        except Exception:pass
    # Only query the selected bonded peer; this is never a nearby-device scan.
    record=await discover()
    if not record:raise RuntimeError('No HFP Handsfree SDP record')
    channel=record[0]
    if type(channel) is not int or not 1<=channel<=30:raise RuntimeError('Invalid peer RFCOMM channel')
    return await open_dlc(channel),channel,False
