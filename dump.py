#!/usr/bin/env python3

import argparse
import sys
import time

import libusb_package
import usb.core
import usb.util

FASTBOOT_CLASS = 0xFF
FASTBOOT_SUBCLASS = 0x42
FASTBOOT_PROTOCOL = 0x03
TIMEOUT_MS = 10000


class FastbootDevice:
    def __init__(self):
        self._backend = libusb_package.get_libusb1_backend()
        self._dev = None
        self._intf = None
        self._ep_in = None
        self._ep_out = None

    def find(self):
        while True:
            for dev in usb.core.find(find_all=True, backend=self._backend):
                try:
                    for cfg in dev:
                        for intf in cfg:
                            if (intf.bInterfaceClass == FASTBOOT_CLASS and
                                intf.bInterfaceSubClass == FASTBOOT_SUBCLASS and
                                intf.bInterfaceProtocol == FASTBOOT_PROTOCOL):
                                self._attach(dev, intf)
                                return
                except Exception:
                    continue
            time.sleep(1)

    def _attach(self, dev, intf):
        try:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                dev.detach_kernel_driver(intf.bInterfaceNumber)
        except (usb.core.USBError, NotImplementedError):
            pass

        dev.set_configuration()
        usb.util.claim_interface(dev, intf.bInterfaceNumber)

        self._ep_out = usb.util.find_descriptor(intf,
            custom_match=lambda e:
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        self._ep_in = usb.util.find_descriptor(intf,
            custom_match=lambda e:
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)

        if not self._ep_out or not self._ep_in:
            raise RuntimeError("Could not find USB endpoints")

        self._dev = dev
        self._intf = intf

    def command(self, cmd):
        self._ep_out.write(cmd.encode(), timeout=TIMEOUT_MS)

        lines = []
        while True:
            try:
                resp = bytes(self._ep_in.read(256, timeout=TIMEOUT_MS))
            except usb.core.USBTimeoutError:
                break

            tag = resp[:4]
            payload = resp[4:].rstrip(b"\x00").decode(errors="replace")

            if tag == b"INFO":
                lines.append(payload)
            elif tag == b"OKAY":
                break
            elif tag == b"FAIL":
                raise RuntimeError("Command failed: %s" % payload)

        return lines

    def release(self):
        if self._dev and self._intf:
            try:
                usb.util.release_interface(self._dev, self._intf.bInterfaceNumber)
            except Exception:
                pass

    @property
    def vid(self):
        return self._dev.idVendor if self._dev else 0

    @property
    def pid(self):
        return self._dev.idProduct if self._dev else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", default="log.txt")
    parser.add_argument("-s", "--silent", action="store_true")
    args = parser.parse_args()

    fb = FastbootDevice()

    try:
        print("Waiting for fastboot device...")
        fb.find()
        print("Found device: %04x:%04x" % (fb.vid, fb.pid))

        print("Dumping pllk log...")
        chunks = fb.command("oem dump_pllk_log")
        log = "".join(chunks).replace("\r\n", "\n").replace("\r", "\n")

        if not args.silent:
            print(log)

        with open(args.output, "w", encoding="utf-8") as f:
            f.write(log)

        print("Saved to %s (%d bytes)" % (args.output, len(log)))

    except KeyboardInterrupt:
        print("\nCancelled")
        return 1
    except RuntimeError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1
    finally:
        fb.release()

    return 0


if __name__ == "__main__":
    sys.exit(main())
