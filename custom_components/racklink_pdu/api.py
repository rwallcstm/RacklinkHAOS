import socket
import time
from .const import MAX_RETRIES

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
        self.timeout = 5.0

    def _connect(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        return s

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

    def _send_command(self, command, subcommand, data=b""):
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

    def _read_response(self, sock):
        header = sock.recv(1)
        if not header or header[0] != 0xfe:
            raise RackLinkAPIError("Invalid response: Missing FE header")

        length_byte = sock.recv(1)
        if not length_byte:
            raise RackLinkAPIError("Invalid response: Missing Length")
        length = length_byte[0]
        body = sock.recv(length + 2)
        if len(body) < length + 2:
            raise RackLinkAPIError("Incomplete response body")

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

    def _login(self, sock):
        creds = f"{self.username}|{self.password}".encode('ascii')
        msg = self._send_command(0x02, 0x01, creds)
        sock.sendall(msg)
        resp = self._read_response(sock)
        if len(resp) < 4 or resp[1] != 0x02 or resp[2] != 0x10:
            raise RackLinkAPIError("Login: unexpected response")
        status = resp[3]
        if status != 0x01:
            raise RackLinkAuthenticationError("Invalid credentials")

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

    def get_outlet_count(self):
        for attempt in range(MAX_RETRIES):
            try:
                sock = self._connect()
                self._login(sock)
                cmd = self._send_command(0x22, 0x02)
                sock.sendall(cmd)
                resp = self._read_response(sock)
                self._check_for_nack(resp)
                if resp[1] == 0x22 and resp[2] == 0x10:
                    data = resp[3:]
                    outlet_status = data[0:16]
                    count = 0
                    for b in outlet_status:
                        if b == ord('C') or b == ord('N'):
                            count += 1
                    return count
                else:
                    raise RackLinkAPIError("Unexpected response for outlet count")
            except (RackLinkAPIError, socket.error):
                time.sleep(1)
                if attempt == MAX_RETRIES - 1:
                    raise
            finally:
                if 'sock' in locals():
                    sock.close()

    def get_outlets_status(self, outlets):
        results = {}
        for o in outlets:
            results[o] = self.get_outlet_status(o)
        return results

    def get_outlet_status(self, outlet):
        for attempt in range(MAX_RETRIES):
            try:
                sock = self._connect()
                self._login(sock)
                cmd = self._send_command(0x20, 0x02, bytes([outlet]))
                sock.sendall(cmd)
                resp = self._read_response(sock)
                self._check_for_nack(resp)
                if resp[1] == 0x20 and resp[2] in (0x10, 0x12, 0x30):
                    state = resp[4]
                    return state == 0x01
                raise RackLinkAPIError("Unexpected outlet status response")
            except (RackLinkAPIError, socket.error):
                time.sleep(1)
                if attempt == MAX_RETRIES - 1:
                    return False
            finally:
                if 'sock' in locals():
                    sock.close()

    def set_outlet_state(self, outlet, on):
        state = 0x01 if on else 0x00
        data = bytes([outlet, state]) + b'0000'
        for attempt in range(MAX_RETRIES):
            try:
                sock = self._connect()
                self._login(sock)
                cmd = self._send_command(0x20, 0x01, data)
                sock.sendall(cmd)
                resp = self._read_response(sock)
                self._check_for_nack(resp)
                if resp[1] == 0x20 and resp[2] == 0x10:
                    return True
                raise RackLinkAPIError("Failed to set outlet state")
            except (RackLinkAPIError, socket.error):
                time.sleep(1)
                if attempt == MAX_RETRIES - 1:
                    return False
            finally:
                if 'sock' in locals():
                    sock.close()
