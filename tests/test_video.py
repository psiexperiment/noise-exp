'''
Tests for detecting whether the psivideo server is running.
'''
import asyncio
import socket
import threading

import pytest
from websockets.asyncio.server import serve

from noise_exp.video import is_psivideo_running


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture
def server_port():
    '''
    A websocket server standing in for psivideo, on a free port.
    '''
    port = free_port()
    started = threading.Event()
    stop = threading.Event()

    async def handler(websocket):
        async for message in websocket:
            pass

    async def run():
        async with serve(handler, 'localhost', port):
            started.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)

    thread = threading.Thread(target=asyncio.run, args=(run(),))
    thread.start()
    started.wait(5)
    yield port
    stop.set()
    thread.join()


def test_running(server_port):
    assert is_psivideo_running(port=server_port)


def test_not_running():
    assert not is_psivideo_running(port=free_port())
