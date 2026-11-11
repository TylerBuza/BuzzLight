# Lytmi / Beelight USB LED controller — wire protocol

Interoperability notes for the USB LED strip kits sold as Lytmi / Beelight
(Artery AT32 microcontroller). These are facts about the device's protocol,
recorded so BuzzLight can talk to the hardware directly.

## Transport

| Item | Value |
|---|---|
| USB ID | VID `0x2E3C`, PID `0x5740` ("Artery AT32 Virtual Com Port", CDC-ACM) |
| Port | Windows: `COMn`; Linux: `/dev/ttyACMn` |
| Baud | 500000, 8N1 |
| Lines | assert DTR and RTS after opening |
| LEDs | 75 RGB LEDs per strip |

The controller sends replies and ACKs. The host can ignore them, but it
should drain the input buffer now and then.

## Frame

```
55 AA 5A  <len: u16 little-endian>  <body: len bytes>
```

`body` is the obfuscated payload:

```
body[0]            checksum  = sum(body[1:]) & 0xFF
body[1]            n ^ 0x31  (n = key length, 3..10)
body[2 : 2+n]      key       (n random bytes)
body[2+n : ]       plain[i] ^ key[i % n]
```

`plain = attr (1 byte) + cmd (1 byte) + data`. The key is random for each
packet and doesn't depend on the data. The controller drops any packet whose
checksum is wrong.

## Messages (`plain` bytes)

| Purpose | plain |
|---|---|
| Heartbeat | `01 00` |
| Query device info | `00 01` |
| Query channels | `00 02` |
| Query capabilities | `00 03` |
| Power on/off | `00 05 01 FF 01 00 <01 on / 00 off>` |
| Brightness (dimmer) | `00 05 02 FF 02 00 <u16le 0..1000>` |
| Solid color | `00 05 04 FF 03 00 R G B` |
| Per-LED frame | `00 05 05 FF E3 00 4B 00` + 75 × `R G B` (225 bytes) |
| Work mode | `00 05 06 FF 03 00 <mode> 00 00` (mode 0 = PC control) |

In a control message, the bytes after `00 05` are
`<ctrl> FF <len u16le> <payload>`. `ctrl` values: 1 power, 2 brightness,
3 color temperature, 4 color, 5 per-LED frame, 6 work mode.

- **Per-LED frames list LEDs from the far end of the strip.** The first
  RGB triple drives the last physical LED.
- **The dimmer scales every output mode.** Map UI brightness 0..255 to
  `round(b * 1000 / 255)`.

## Session

1. Open the port, assert DTR and RTS, wait about 300 ms, then drain the input.
2. Wake-up: device info → channels → power on → capabilities, then a few
   heartbeats. Send these about 50 ms apart.
3. Set brightness 0, power on, brightness 0 again, then work mode PC. The
   zero dimmer stops the strip flashing its previous state on reconnect.
4. Keep sending heartbeats (about every 150 ms). Without them the controller
   leaves PC mode and goes back to its own effects.
5. The controller sometimes resets the dimmer, so re-send brightness and the
   current color or frame about twice a second, even when nothing changed.
6. Sending packets faster than about 66 per second doesn't help.
