import asyncio
import logging
from .const import MAX_RETRIES, RECONNECT_DELAY

_LOGGER = logging.getLogger(__name__)

class RackLinkAPIError(Exception):
    pass

class RackLinkAuthenticationError(RackLinkAPIError):
    pass

class RackLinkNACKError(RackLinkAPIError):
    def __init__(self, error_code, message):
        super().__init__(message)
        self.error_code = error_code

class RackLinkAPI:
    def __init__(self, host, port=60000, username="user", password="cstmcstm"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.reader = None
        self.writer = None
        self.connected = False
        self._lock = asyncio.Lock()
        self._response_future = None
        self._read_task = None
        self._stopped = False

    async def connect_persistent(self):
        """Connect and login, start read loop, and perform initial handshake."""
        await self.close()
        for attempt in range(MAX_RETRIES):
            try:
                _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                await self._login()
                self.connected = True
                self._stopped = False
                self._read_task = asyncio.create_task(self._read_loop())
                # After login, we either wait for the device to send a PING or we initiate a ping to finalize handshake.
                # Send a ping to ensure the device is ready.
                _LOGGER.debug("Sending initial ping after login.")
                await self.ping()
                _LOGGER.debug("Initial handshake complete.")
                return
            except Exception as e:
                _LOGGER.debug("Connection attempt failed: %s", e)
                await self.close()
                await asyncio.sleep(RECONNECT_DELAY)
        raise RackLinkAPIError("Could not connect and login after retries")

    async def close(self):
        self._stopped = True
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass
        self.writer = None
        self.reader = None
        self.connected = False

    async def _login(self):
        creds = f"{self.username}|{self.password}".encode('ascii')
        resp = await self._send_and_receive(0x02, 0x01, creds)
        if len(resp) < 4 or resp[1] != 0x02 or resp[2] != 0x10:
            raise RackLinkAPIError("Login: unexpected response")
        status = resp[3]
        if status != 0x01:
            raise RackLinkAuthenticationError("Invalid credentials")
        _LOGGER.debug("Login successful.")

    def _calculate_checksum(self, data):
        sum_val = 0
        for b in data:
            sum_val += b
        return sum_val & 0x7f

    def _escape_data(self, data):
        escaped = bytearray()
        for b in data:
            if b in (0xfe, 0xff, 0xfd):
                escaped.append(0xfd)
                escaped.append(b ^ 0xff)
            else:
                escaped.append(b)
        return escaped

    def _form_message(self, command, subcommand, data=b""):
        destination = 0x00
        data_envelope = bytearray([destination, command, subcommand]) + data
        length = len(data_envelope)
        header = 0xfe
        tail = 0xff
        chk_data = bytearray([header, length]) + data_envelope
        checksum = self._calculate_checksum(chk_data)
        escaped_envelope = self._escape_data(data_envelope)
        message = bytearray([header, length]) + escaped_envelope + bytearray([checksum, tail])
        return message

    def _unescape(self, data):
        result = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b == 0xfd:
                i += 1
                if i >= len(data):
                    raise RackLinkAPIError("Invalid escape sequence")
                escaped_val = data[i]
                val = escaped_val ^ 0xff
                result.append(val)
            else:
                result.append(b)
            i += 1
        return result

    def _check_for_nack(self, resp):
        if len(resp) > 3 and resp[1] == 0x10 and resp[2] == 0x10:
            error_code = resp[3]
            error_msg = {
                0x01: 'Bad CRC on previous command',
                0x02: 'Bad Length on previous command',
                0x03: 'Bad Escape sequence on previous command',
                0x04: 'Previous command invalid',
                0x05: 'Previous sub-command invalid',
                0x06: 'Previous command incorrect byte count',
                0x07: 'Invalid data bytes in previous command',
                0x08: 'Invalid Credentials (need to login again)',
                0x10: 'Unknown Error',
                0x11: 'Access Denied (EPO)'
            }.get(error_code, f"Unknown error code {error_code}")
            raise RackLinkNACKError(error_code, error_msg)

    async def _read_message(self):
        header = await self.reader.readexactly(1)
        if header[0] != 0xfe:
            raise RackLinkAPIError("Invalid response: Missing FE header")
        length_byte = await self.reader.readexactly(1)
        length = length_byte[0]
        body = await self.reader.readexactly(length + 2)
        tail = body[-1]
        chksum = body[-2]
        data_envelope_escaped = body[0:-2]
        if tail != 0xff:
            raise RackLinkAPIError("Missing FF tail")

        data_envelope = self._unescape(data_envelope_escaped)
        calc_checksum = self._calculate_checksum(bytearray([0xfe, length]) + data_envelope)
        if calc_checksum != chksum:
            raise RackLinkAPIError("Checksum mismatch")
        return data_envelope

    async def _read_loop(self):
        _LOGGER.debug("Read loop started.")
        try:
            while not self._stopped and self.connected:
                msg = await self._read_message()
                # Handle PING from device
                if msg[1] == 0x01 and msg[2] == 0x01:
                    _LOGGER.debug("Received PING from device, sending PONG.")
                    pong = self._form_message(0x01, 0x10)
                    self.writer.write(pong)
                    await self.writer.drain()
                    continue

                self._check_for_nack(msg)

                if self._response_future and not self._response_future.done():
                    self._response_future.set_result(msg)
        except (asyncio.CancelledError, asyncio.IncompleteReadError, RackLinkAPIError) as e:
            _LOGGER.debug("Read loop ended due to error: %s", e)
            self.connected = False
        finally:
            self.connected = False
            _LOGGER.debug("Read loop exited.")

    async def _send_and_receive(self, command, subcommand, data=b""):
        if not self.connected:
            await self.connect_persistent()

        async with self._lock:
            if self._response_future and not self._response_future.done():
                self._response_future.cancel()

            self._response_future = asyncio.get_event_loop().create_future()
            message = self._form_message(command, subcommand, data)
            for attempt in range(MAX_RETRIES):
                try:
                    _LOGGER.debug("Sending command: cmd=0x%02X sub=0x%02X data=%s", command, subcommand, data.hex())
                    self.writer.write(message)
                    await self.writer.drain()
                    resp = await asyncio.wait_for(self._response_future, timeout=10)
                    return resp
                except (asyncio.TimeoutError, RackLinkAPIError, asyncio.IncompleteReadError):
                    _LOGGER.debug("Failed attempt to send/receive, retrying...")
                    await self.close()
                    await asyncio.sleep(RECONNECT_DELAY)
                    await self.connect_persistent()
                    self._response_future = asyncio.get_event_loop().create_future()
                    continue
            raise RackLinkAPIError("Failed to get response after retries")

    async def ping(self):
        resp = await self._send_and_receive(0x01, 0x01)
        if resp[1] == 0x01 and resp[2] == 0x10:
            _LOGGER.debug("Ping successful, received Pong.")
            return True
        _LOGGER.debug("Ping failed.")
        return False

    async def get_outlet_count(self):
        resp = await self._send_and_receive(0x22, 0x02)
        if resp[1] == 0x22 and resp[2] == 0x10:
            data = resp[3:]
            outlet_status = data[0:16]
            count = 0
            for b in outlet_status:
                if b == ord('C') or b == ord('N'):
                    count += 1
            _LOGGER.debug("Outlet count: %d", count)
            return count
        raise RackLinkAPIError("Unexpected response for outlet count")

    async def get_outlets_status(self, outlets):
        results = {}
        for o in outlets:
            results[o] = await self.get_outlet_status(o)
        return results

    async def get_outlet_status(self, outlet):
        resp = await self._send_and_receive(0x20, 0x02, bytes([outlet]))
        if resp[1] == 0x20 and resp[2] in (0x10, 0x12, 0x30):
            state = resp[4]
            on = state == 0x01
            _LOGGER.debug("Outlet %d status: %s", outlet, "ON" if on else "OFF")
            return on
        raise RackLinkAPIError("Unexpected outlet status response")

    async def set_outlet_state(self, outlet, on):
        state = 0x01 if on else 0x00
        data = bytes([outlet, state]) + b'0000'
        resp = await self._send_and_receive(0x20, 0x01, data)
        if resp[1] == 0x20 and resp[2] == 0x10:
            _LOGGER.debug("Successfully set outlet %d to %s", outlet, "ON" if on else "OFF")
            return True
        raise RackLinkAPIError("Failed to set outlet state")
