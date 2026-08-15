"""Tiny JDWP client: invoke static RecompAgent.install() via DexClassLoader."""
from __future__ import annotations

import socket
import struct
from typing import Any, Optional

HANDSHAKE = b"JDWP-Handshake"


class JdwpError(RuntimeError):
    pass


class Jdwp:
    def __init__(self, host: str, port: int, timeout: float = 8.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.sock.sendall(HANDSHAKE)
        got = self._recv_exact(len(HANDSHAKE))
        if got != HANDSHAKE:
            raise JdwpError(f"bad handshake: {got!r}")
        self._id = 0
        self.oid_sz = 8
        self.rid_sz = 8
        self.mid_sz = 8
        self.fid_sz = 8
        self._events: list[bytes] = []
        self._idsizes()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise JdwpError("jdwp socket closed")
            buf += chunk
        return buf

    def _pkt(self, cmd_set: int, cmd: int, data: bytes = b"") -> bytes:
        self._id += 1
        pkt_id = self._id
        header = struct.pack(">IIBB", 11 + len(data), pkt_id, 0, cmd_set)
        self.sock.sendall(header + bytes([cmd]) + data)
        while True:
            raw_len = self._recv_exact(4)
            (length,) = struct.unpack(">I", raw_len)
            rest = self._recv_exact(length - 4)
            rid, flags, err = struct.unpack(">IBH", rest[:7])
            body = rest[7:]
            if flags & 0x80:
                if rid != pkt_id:
                    continue
                if err != 0:
                    raise JdwpError(f"jdwp error {err} cmd={cmd_set}/{cmd}")
                return body
            # VM event (command packet). cmdset/cmd sit where error was parsed.
            self._events.append(rest)

    def _idsizes(self) -> None:
        body = self._pkt(1, 7)
        self.fid_sz, self.mid_sz, self.oid_sz, self.rid_sz, _frame = struct.unpack(
            ">IIIII", body[:20]
        )

    def _pack_id(self, n: int, sz: int) -> bytes:
        if sz == 4:
            return struct.pack(">I", n)
        if sz == 8:
            return struct.pack(">Q", n)
        raise JdwpError(f"id size {sz}")

    def _unpack_id(self, data: bytes, sz: int) -> tuple[int, bytes]:
        if sz == 4:
            return struct.unpack(">I", data[:4])[0], data[4:]
        if sz == 8:
            return struct.unpack(">Q", data[:8])[0], data[8:]
        raise JdwpError(f"id size {sz}")

    def suspend(self) -> None:
        self._pkt(1, 8)

    def resume(self) -> None:
        self._pkt(1, 9)

    def classes_by_sig(self, sig: str) -> list[int]:
        raw = sig.encode("utf-8")
        body = self._pkt(1, 2, struct.pack(">I", len(raw)) + raw)
        (count,) = struct.unpack(">I", body[:4])
        off = 4
        ids = []
        for _ in range(count):
            off += 1  # refTypeTag
            cid, rest = self._unpack_id(body[off:], self.rid_sz)
            off = len(body) - len(rest)
            off += 4  # status
            ids.append(cid)
        return ids

    def class_id(self, sig: str) -> int:
        ids = self.classes_by_sig(sig)
        if not ids:
            raise JdwpError(f"class not loaded: {sig}")
        return ids[0]

    def methods(self, type_id: int) -> list[tuple[int, str, str]]:
        body = self._pkt(2, 5, self._pack_id(type_id, self.rid_sz))
        (count,) = struct.unpack(">I", body[:4])
        data = body[4:]
        out = []
        for _ in range(count):
            mid, data = self._unpack_id(data, self.mid_sz)
            n = struct.unpack(">I", data[:4])[0]
            name = data[4 : 4 + n].decode("utf-8")
            data = data[4 + n :]
            n = struct.unpack(">I", data[:4])[0]
            sig = data[4 : 4 + n].decode("utf-8")
            data = data[4 + n :]
            data = data[4:]  # modbits
            out.append((mid, name, sig))
        return out

    def method(self, type_id: int, name: str, sig: str) -> int:
        for mid, n, s in self.methods(type_id):
            if n == name and s == sig:
                return mid
        raise JdwpError(f"method {name}{sig} not on type {type_id}")

    def create_string(self, s: str) -> int:
        raw = s.encode("utf-8")
        body = self._pkt(1, 11, struct.pack(">I", len(raw)) + raw)
        sid, _ = self._unpack_id(body, self.oid_sz)
        return sid

    def all_threads(self) -> list[int]:
        body = self._pkt(1, 4)
        (count,) = struct.unpack(">I", body[:4])
        data = body[4:]
        ids = []
        for _ in range(count):
            tid, data = self._unpack_id(data, self.oid_sz)
            ids.append(tid)
        return ids

    def thread_name(self, tid: int) -> str:
        body = self._pkt(11, 1, self._pack_id(tid, self.oid_sz))
        n = struct.unpack(">I", body[:4])[0]
        return body[4 : 4 + n].decode("utf-8", "replace")

    def pick_thread(self) -> int:
        named = []
        for tid in self.all_threads():
            try:
                name = self.thread_name(tid)
            except JdwpError:
                continue
            named.append((name, tid))
        for want in ("main", "pixi-recomp"):
            for name, tid in named:
                if name == want:
                    return tid
        if not named:
            raise JdwpError("no threads")
        return named[0][1]

    def suspend_thread(self, tid: int) -> None:
        try:
            self._pkt(11, 2, self._pack_id(tid, self.oid_sz))
        except JdwpError:
            pass

    def candidate_threads(self) -> list[int]:
        prefer = []
        rest = []
        for tid in self.all_threads():
            try:
                name = self.thread_name(tid)
            except JdwpError:
                continue
            if name.startswith("binder:") or name in (
                "Signal Catcher",
                "JDWP",
                "ADB-JDWP Connection Control Thread",
                "ReferenceQueueDaemon",
                "FinalizerDaemon",
                "FinalizerWatchdogDaemon",
                "HeapTaskDaemon",
                "Jit thread pool worker thread 0",
                "Profile Saver",
                "RenderThread",
            ):
                continue
            if name == "main":
                prefer.insert(0, tid)
            else:
                rest.append(tid)
        return prefer + rest

    def _value(self, tag: int, obj: int) -> bytes:
        return bytes([tag]) + self._pack_id(obj, self.oid_sz)

    def _bool(self, v: bool) -> bytes:
        return bytes([90, 1 if v else 0])

    def _read_value(self, data: bytes) -> tuple[Any, bytes]:
        tag = data[0]
        data = data[1:]
        if tag in (76, 115, 116, 91, 66, 70, 83, 73):  # L s t [ B F S I objects-ish
            if tag in (66,):  # byte
                return data[0], data[1:]
            if tag == 73:  # int
                return struct.unpack(">i", data[:4])[0], data[4:]
            if tag == 90:  # boolean
                return bool(data[0]), data[1:]
            oid, data = self._unpack_id(data, self.oid_sz)
            return oid, data
        if tag == 90:
            return bool(data[0]), data[1:]
        if tag == 73:
            return struct.unpack(">i", data[:4])[0], data[4:]
        if tag == 74:  # long
            return struct.unpack(">q", data[:8])[0], data[8:]
        if tag == 86:  # void
            return None, data
        # object-like default
        oid, data = self._unpack_id(data, self.oid_sz)
        return oid, data

    def invoke_static(
        self, thread: int, clazz: int, method: int, args: list[bytes], options: int = 0
    ) -> Any:
        data = (
            self._pack_id(clazz, self.rid_sz)
            + self._pack_id(thread, self.oid_sz)
            + self._pack_id(method, self.mid_sz)
            + struct.pack(">I", len(args))
            + b"".join(args)
            + struct.pack(">I", options)
        )
        body = self._pkt(3, 3, data)
        val, rest = self._read_value(body)
        # exception object follows
        exc, _ = self._read_value(rest)
        if exc:
            raise JdwpError(f"invoke threw {self._exc_name(exc)}")
        return val

    def invoke_obj(
        self, thread: int, obj: int, clazz: int, method: int, args: list[bytes], options: int = 0
    ) -> Any:
        data = (
            self._pack_id(obj, self.oid_sz)
            + self._pack_id(thread, self.oid_sz)
            + self._pack_id(clazz, self.rid_sz)
            + self._pack_id(method, self.mid_sz)
            + struct.pack(">I", len(args))
            + b"".join(args)
            + struct.pack(">I", options)
        )
        body = self._pkt(9, 6, data)
        val, rest = self._read_value(body)
        exc, _ = self._read_value(rest)
        if exc:
            raise JdwpError(f"invoke threw {self._exc_name(exc)}")
        return val

    def _exc_name(self, oid: int) -> str:
        try:
            body = self._pkt(9, 1, self._pack_id(oid, self.oid_sz))
            tag = body[0]
            tid, _ = self._unpack_id(body[1:], self.rid_sz)
            sig_body = self._pkt(2, 1, self._pack_id(tid, self.rid_sz))
            n = struct.unpack(">I", sig_body[:4])[0]
            return sig_body[4 : 4 + n].decode("utf-8", "replace")
        except Exception:
            return f"object {oid}"

    def new_instance(
        self, thread: int, clazz: int, ctor: int, args: list[bytes], options: int = 0
    ) -> int:
        data = (
            self._pack_id(clazz, self.rid_sz)
            + self._pack_id(thread, self.oid_sz)
            + self._pack_id(ctor, self.mid_sz)
            + struct.pack(">I", len(args))
            + b"".join(args)
            + struct.pack(">I", options)
        )
        body = self._pkt(3, 4, data)
        val, rest = self._read_value(body)
        exc, _ = self._read_value(rest)
        if exc:
            raise JdwpError(f"newInstance threw {self._exc_name(exc)}")
        return int(val)

    def new_array(self, array_type: int, length: int) -> int:
        body = self._pkt(4, 1, self._pack_id(array_type, self.rid_sz) + struct.pack(">I", length))
        oid, _ = self._unpack_id(body[1:], self.oid_sz)
        return oid

    def set_bytes(self, array_oid: int, data: bytes) -> None:
        # ArrayReference.SetValues — byte elements are untagged in some VMs;
        # ART wants tagged values (B + byte).
        payload = self._pack_id(array_oid, self.oid_sz) + struct.pack(">II", 0, len(data))
        payload += data  # primitive byte[] is untagged in JDWP
        self._pkt(13, 3, payload)


    def line_table(self, type_id: int, method_id: int) -> list[tuple[int, int]]:
        body = self._pkt(
            6, 1, self._pack_id(type_id, self.rid_sz) + self._pack_id(method_id, self.mid_sz)
        )
        # start, end long, then count
        data = body[16:]
        (count,) = struct.unpack(">I", data[:4])
        data = data[4:]
        rows = []
        for _ in range(count):
            idx = struct.unpack(">Q", data[:8])[0]
            line = struct.unpack(">I", data[8:12])[0]
            data = data[12:]
            rows.append((idx, line))
        return rows

    def set_breakpoint(self, type_id: int, method_id: int, index: int = 0) -> int:
        loc = (
            bytes([1])
            + self._pack_id(type_id, self.rid_sz)
            + self._pack_id(method_id, self.mid_sz)
            + struct.pack(">Q", index)
        )
        data = bytes([2, 2]) + struct.pack(">I", 1) + bytes([7]) + loc
        body = self._pkt(15, 1, data)
        return struct.unpack(">I", body[:4])[0]

    def clear_breakpoint(self, request_id: int) -> None:
        self._pkt(15, 3, bytes([2]) + struct.pack(">I", request_id))

    def _read_packet(self) -> tuple[int, int, bytes]:
        raw_len = self._recv_exact(4)
        (length,) = struct.unpack(">I", raw_len)
        rest = self._recv_exact(length - 4)
        rid, flags = struct.unpack(">IB", rest[:5])
        return rid, flags, rest[5:]

    def wait_breakpoint(self, timeout: float = 8.0) -> int:
        self.sock.settimeout(timeout)
        while True:
            if self._events:
                rest = self._events.pop(0)
                # rest is flags-payload starting at id? stored as rest from _pkt
                # stored rest = id(4)+flags(1)+cmdset+cmd+data  wait we stored rest after length
                # in _pkt: rest = id, flags, err/cmd, body
                flags = rest[4]
                payload = rest[5:]
            else:
                _rid, flags, payload = self._read_packet()
            if flags & 0x80:
                continue
            cmd_set, cmd = payload[0], payload[1]
            data = payload[2:]
            if cmd_set != 64 or cmd != 100:
                continue
            # suspendPolicy + events
            data = data[1:]
            (n,) = struct.unpack(">I", data[:4])
            data = data[4:]
            for _ in range(n):
                kind = data[0]
                data = data[1:]
                _req = struct.unpack(">I", data[:4])[0]
                data = data[4:]
                if kind == 2:  # BREAKPOINT
                    tid, _rest = self._unpack_id(data, self.oid_sz)
                    return tid
                # skip unknown
                raise JdwpError(f"unexpected event kind {kind}")
        raise JdwpError("no breakpoint")


def inject_recomp_agent(host: str, port: int, dex_bytes: bytes, opt_dir: str = "") -> None:
    j = Jdwp(host, port)
    try:
        bp_cls = None
        bp_mid = None
        choreo = j.class_id("Landroid/view/Choreographer;")
        for mid, name, sig in j.methods(choreo):
            if name == "doFrame" and sig.startswith("(J"):
                bp_cls, bp_mid = choreo, mid
                break
        if bp_mid is None:
            handler = j.class_id("Landroid/os/Handler;")
            bp_cls = handler
            bp_mid = j.method(handler, "dispatchMessage", "(Landroid/os/Message;)V")
        lines = j.line_table(bp_cls, bp_mid)
        index = lines[0][0] if lines else 0
        req = j.set_breakpoint(bp_cls, bp_mid, index)
        try:
            thread = j.wait_breakpoint(12.0)
        finally:
            try:
                j.clear_breakpoint(req)
            except JdwpError:
                pass

        class_cls = j.class_id("Ljava/lang/Class;")
        cl_cls = j.class_id("Ljava/lang/ClassLoader;")
        method_cls = j.class_id("Ljava/lang/reflect/Method;")
        obj_arr = j.class_id("[Ljava/lang/Object;")
        class_arr = j.class_id("[Ljava/lang/Class;")

        for_name = j.method(
            class_cls,
            "forName",
            "(Ljava/lang/String;ZLjava/lang/ClassLoader;)Ljava/lang/Class;",
        )
        at_cls = j.class_id("Landroid/app/ActivityThread;")
        current_app = j.method(
            at_cls, "currentApplication", "()Landroid/app/Application;"
        )
        ctx_cls = j.class_id("Landroid/content/Context;")
        get_cl_ctx = j.method(ctx_cls, "getClassLoader", "()Ljava/lang/ClassLoader;")
        app = j.invoke_static(thread, at_cls, current_app, [])
        parent_cl = j.invoke_obj(thread, app, ctx_cls, get_cl_ctx, [])
        load_class = j.method(cl_cls, "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;")
        get_method = j.method(
            class_cls,
            "getMethod",
            "(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;",
        )
        invoke = j.method(
            method_cls,
            "invoke",
            "(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;",
        )

        composer = j.invoke_static(
            thread,
            class_cls,
            for_name,
            [
                j._value(115, j.create_string("androidx.compose.runtime.ComposerKt")),
                j._bool(True),
                j._value(76, int(parent_cl)),
            ],
        )

        byte_arr_t = j.class_id("[B")
        raw = j.new_array(byte_arr_t, len(dex_bytes))
        j.set_bytes(raw, dex_bytes)
        buf_cls = j.class_id("Ljava/nio/ByteBuffer;")
        wrap = j.method(buf_cls, "wrap", "([B)Ljava/nio/ByteBuffer;")
        buf = j.invoke_static(thread, buf_cls, wrap, [j._value(91, raw)])
        dex_cls = j.class_id("Ldalvik/system/InMemoryDexClassLoader;")
        ctor = j.method(
            dex_cls,
            "<init>",
            "(Ljava/nio/ByteBuffer;Ljava/lang/ClassLoader;)V",
        )
        loader = j.new_instance(
            thread,
            dex_cls,
            ctor,
            [
                j._value(76, int(buf)),
                j._value(76, int(parent_cl)),
            ],
        )
        agent_cls = j.invoke_obj(
            thread,
            loader,
            cl_cls,
            load_class,
            [j._value(115, j.create_string("pixi.recomp.RecompAgent"))],
        )
        empty_classes = j.new_array(class_arr, 0)
        install = j.invoke_obj(
            thread,
            agent_cls,
            class_cls,
            get_method,
            [
                j._value(115, j.create_string("install")),
                j._value(91, empty_classes),
            ],
        )
        empty_objs = j.new_array(obj_arr, 0)
        j.invoke_obj(
            thread,
            install,
            method_cls,
            invoke,
            [j._value(76, 0), j._value(91, empty_objs)],
        )
    finally:
        try:
            j.resume()
        except Exception:
            pass
        j.close()
