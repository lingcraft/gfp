from re import sub, search
from struct import pack, pack_into, unpack_from
from sys import argv
from _cffi_backend import buffer

secret_key = b"taomee_konfu_rock77#!%&~\x00"
key_len, head_len, serial_num, growth_num = len(secret_key), 18, 1, 0
user_id = 0
pending = bytearray()


class Packet:
    def __init__(self, packet=None, cmd_id=None, body=None):
        self.length = self.cmd_id = self.user_id = self.result = self.growth_num = 0
        self.body = bytearray()
        if packet is not None:
            packet = self.to_bytearray(packet)
            if len(packet) >= head_len:
                self.length, self.cmd_id, self.user_id, self.result, self.growth_num = unpack_from("!IHIII", packet)
                self.body = packet[head_len:]
        elif cmd_id is not None:
            self.cmd_id = cmd_id
            self.body = self.to_bytearray(body)

    def data(self):
        head = pack("!IHIII", self.length, self.cmd_id, self.user_id, self.result, self.growth_num)
        return head + self.body

    @staticmethod
    def to_bytearray(data: str | bytearray | bytes | buffer | None):
        if data is None:
            return bytearray()
        if isinstance(data, str):
            # 支持带标注的输入，如：“学习技能：0000000000000004670000000000000000
            # {00009A96:拉姆ID}{00000003:技能类别}{3:技能等级}”
            # 大括号里的值：0 开头 → 16 进制、按写的位数原样使用（仅补齐偶数位）——
            # {01}=1字节、{001}=2字节、{00009A96}=4字节；
            # 非 0 开头：含 [a-fA-F] 按 16 进制、纯数字按 10 进制，统一转 4 字节（8 位、前补 0）。
            def to_field(match):
                value = match.group(1)
                if value == "":
                    return value
                if value.startswith("0"):
                    return "0" + value if len(value) % 2 else value
                base = 16 if search(r"[a-fA-F]", value) else 10
                return f"{int(value, base):08X}"

            data = sub(r"{([^}:]*)(?::[^}]*)?}", to_field, data.split("：", 1)[-1])
            return bytearray.fromhex(data)
        return bytearray(data)

    @staticmethod
    def from_hex(packet: str):
        packet = bytearray.fromhex(packet)
        if packet.startswith(b"\x00\x00"):
            pack_into("!I", packet, 6, user_id)
        return packet

    def get_serial_num(self):
        global growth_num, serial_num
        self.length, self.user_id, self.growth_num = len(self.body) + head_len + 1, user_id, growth_num
        growth_num = (growth_num + 1) & 0xFFFFFFFF
        if self.cmd_id == 999:
            serial_num = 0
        else:
            crc = 0
            for byte in self.body:
                crc ^= byte
            # 计算发送包序列号
            serial_num = (serial_num - serial_num // 7 + 151 + (self.length - 1) % 13 + self.cmd_id % 23 + crc) & 0xFFFFFFFF
        self.result = serial_num

    def encrypt(self, is_get_serial_num: bool = True):
        if is_get_serial_num:
            self.get_serial_num()
        res = bytearray(len(self.body) + 1)
        key_index = 0
        for index in range(len(self.body)):
            res[index] = self.body[index] ^ secret_key[key_index % key_len]
            key_index += 1
            if key_index > key_len:
                key_index = 0
        for index in range(len(res) - 1, 0, -1):
            res[index] |= res[index - 1] >> 3
            res[index - 1] = (res[index - 1] << 5) % 256
        res[0] |= 3
        self.body = res
        return self

    def decrypt(self):
        if len(self.body) == 0:
            return self
        res = bytearray(len(self.body) - 1)
        key_index = 0
        for index in range(len(res)):
            res[index] = (self.body[index] >> 5) | (self.body[index + 1] << 3) % 256
            res[index] ^= secret_key[key_index % key_len]
            key_index += 1
            if key_index > key_len:
                key_index = 0
        self.body = res
        return self


def get_input(tip: str):
    print(f"请输入{tip}：")
    lines = []
    for line in iter(lambda: input(), ""):
        if line.strip().lower() in ("reset", "clear", "重置", "清空"):
            pending.clear()
            print("[i] 已清空断包缓冲区")
            continue
        lines.append(bytes.fromhex(line))
    return lines


def result(operate, lines):
    return "\n".join([operate(line) for line in lines])


def split_packets(data):
    packets, offset, total = [], 0, len(data)
    while offset + head_len <= total:
        length = unpack_from("!I", data, offset)[0]
        if length < head_len or length > 65535:
            break
        if offset + length > total:
            break
        packets.append(bytes(data[offset:offset + length]))
        offset += length
    return packets, bytes(data[offset:])


def stream_result(operate, lines):
    global pending
    stream = bytes(pending) + b"".join(lines)
    packets, rest = split_packets(stream)
    pending = bytearray(rest)
    out = [operate(packet) for packet in packets]
    tip = f"[i] 切出 {len(packets)} 条包"
    if rest:
        tip += f"；末尾 {len(rest)} 字节不成整包，已留存，下次粘贴会接在最前面（输入 reset 清空）"
    out.append(tip)
    return "\n".join(out)


def decrypt_operate(packet):
    packet = Packet(packet)
    if packet.cmd_id != 1001 or packet.length > 200:
        packet.decrypt()
    return packet.data().hex().upper()


def decrypt():
    lines = get_input("封包密文（可粘包 / 断包，多行会拼成一整条流）")
    return stream_result(decrypt_operate, lines)


def decode():
    lines = get_input("需要解码数据")
    operate = lambda line: line.rstrip(b'\x00').decode()
    return result(operate, lines)


def extern():
    if len(argv) > 1:
        func = None
        match argv[1]:
            case "decrypt":
                func = decrypt
            case "decode":
                func = decode
            case _:
                return
        while True:
            res = func()
            if res:
                print(f"结果：\n{res}\n")


if __name__ == "__main__":
    # 外部调用
    extern()
