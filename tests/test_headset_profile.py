import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).parent.parent/'src'/'app'))
from headset_profile import ChannelCache,open_channel

class ProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.cache=ChannelCache(Path(self.temp.name)/'channel.json')
    def tearDown(self):self.temp.cleanup()
    async def test_verified_channel_skips_service_discovery(self):
        self.cache.save('airpods',2);connect=AsyncMock(return_value='dlc');discover=AsyncMock()
        self.assertEqual(await open_channel('airpods',self.cache,connect,discover),('dlc',2,True))
        discover.assert_not_called();connect.assert_awaited_once_with(2)
    async def test_stale_channel_falls_back_to_same_peer(self):
        self.cache.save('airpods',2);connect=AsyncMock(side_effect=[ValueError('rejected'),'dlc'])
        discover=AsyncMock(return_value=(3,))
        self.assertEqual(await open_channel('airpods',self.cache,connect,discover),('dlc',3,False))
        self.assertEqual(connect.await_count,2);discover.assert_awaited_once()
    async def test_other_peer_never_reuses_cache(self):
        self.cache.save('another',2);connect=AsyncMock(return_value='dlc');discover=AsyncMock(return_value=(4,))
        self.assertEqual(await open_channel('airpods',self.cache,connect,discover),('dlc',4,False))
        connect.assert_awaited_once_with(4)
    def test_invalid_cache_and_channel_rejected(self):
        for content in ('bad','[]','{"version":1,"target":"airpods","channel":99}'):
            self.cache.path.write_text(content);self.assertIsNone(self.cache.get('airpods'))
        with self.assertRaises(ValueError):self.cache.save('airpods',False)
    async def test_cancel_not_swallowed_by_cache_fallback(self):
        self.cache.save('airpods',2);discover=AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            await open_channel('airpods',self.cache,AsyncMock(side_effect=asyncio.CancelledError),discover)
        discover.assert_not_called()

if __name__=='__main__':unittest.main()
