"""Caller: rings your phone through Telegram using a SECOND Telegram account (userbot).

Telegram's Bot API cannot place calls, so we log in a second account via Telethon and
request a 1-to-1 call to your main account. That makes your phone ring like a real call.
EXPERIMENTAL: it uses Telegram's raw call-request API; it rings but carries no audio.
The spoken reason is sent as a text/message right before the ring.

One-time login:  python -m agents.caller --login
"""
import asyncio
import hashlib
import os
import random
import sys
from config import TG_API_ID, TG_API_HASH, TG_CALL_TARGET

SESSION = os.path.join(os.path.dirname(os.path.dirname(__file__)), "caller_session")


def configured() -> bool:
    return bool(TG_API_ID and TG_API_HASH and TG_CALL_TARGET)


async def ring(reason: str = "") -> bool:
    if not configured():
        return False
    from telethon import TelegramClient, functions, types, utils
    async with TelegramClient(SESSION, TG_API_ID, TG_API_HASH) as client:
        if not await client.is_user_authorized():
            print("Caller session not logged in. Run: python -m agents.caller --login")
            return False
        target = await client.get_input_entity(TG_CALL_TARGET)
        if reason:
            await client.send_message(target, f"📞 Study call: {reason}")
        dh = await client(functions.messages.GetDhConfigRequest(version=0, random_length=256))
        p = int.from_bytes(dh.p, "big")
        a = int.from_bytes(os.urandom(256), "big")
        g_a = pow(dh.g, a, p).to_bytes(256, "big")
        await client(functions.phone.RequestCallRequest(
            user_id=utils.get_input_user(target),   # needs InputUser, not InputPeerUser
            random_id=random.randint(1, 2**31 - 1),
            g_a_hash=hashlib.sha256(g_a).digest(),
            protocol=types.PhoneCallProtocol(
                min_layer=65, max_layer=92, udp_p2p=True, udp_reflector=True,
                library_versions=["3.0.0"]),
        ))
        return True


if __name__ == "__main__":
    if "--login" in sys.argv:
        from telethon import TelegramClient
        async def _login():
            async with TelegramClient(SESSION, TG_API_ID, TG_API_HASH) as c:
                me = await c.get_me()
                print("Logged in as", me.first_name)
        asyncio.run(_login())
    else:
        print("ring ->", asyncio.run(ring("test call from placement agents")))
