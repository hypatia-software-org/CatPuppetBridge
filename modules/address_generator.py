"""Generate ULA IPv6 addresses for WebIRC"""

import ipaddress
import hashlib

def ula_address_from_string(input_string: str) -> str:
    """
    Hash a string into a single deterministic IPv6 address in fd00::/8 (ULA).
    """
    # Use SHA-1 hash to get 128 bits
    hash_bytes = hashlib.sha1(input_string.encode()).digest()
    addr_int = int.from_bytes(hash_bytes[:16], byteorder='big')

    # Force the address into the fd00::/8 range
    addr_int &= (1 << 121) - 1        # Clear top 7 bits
    addr_int |= 0xfd << 120           # Set top 8 bits to 0xfd (ULA)

    return str(ipaddress.IPv6Address(addr_int))
