#!/usr/bin/env python3
"""
LeadFlow AI — Localhost to VPS Port Forwarder
Forwards http://127.0.0.1:8000 to the native VPS instance at http://192.168.252.2:80
"""
import asyncio
import sys

TARGET_HOST = "192.168.252.2"
TARGET_PORT = 80
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8000

async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
    try:
        remote_reader, remote_writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
    except Exception as e:
        client_writer.close()
        await client_writer.wait_closed()
        return

    await asyncio.gather(
        pipe(client_reader, remote_writer),
        pipe(remote_reader, client_writer),
        return_exceptions=True
    )

async def main():
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    print(f"LeadFlow AI Proxy active: http://{LISTEN_HOST}:{LISTEN_PORT} -> http://{TARGET_HOST}:{TARGET_PORT}")
    sys.stdout.flush()
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
