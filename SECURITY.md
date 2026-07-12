# Security

framewall scans screenshots for visually-embedded prompt injection before a
vision agent acts on them, which means its whole job is decoding images an
attacker may have crafted. Decoding goes through Pillow, text extraction
through an optional local tesseract install. It never executes anything from
an image, and it never talks to the network.

The image decoders are the attack surface. A file built to crash or hang the
scanner (decompression bombs, malformed chunks), to exhaust memory, or to
smuggle terminal escape sequences into the report is a vulnerability in
framewall. So is a verdict-integrity bug: framewall is a security gate, so
anything that makes it report CLEAN without actually scanning - a check that
silently didn't run, an unreadable file graded as safe - gets treated as
security, not polish. Evasion of the detectors by a payload a reasonable
person would expect them to catch is welcome too; include the image.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's private
reporting instead:

https://github.com/munzzyy/framewall/security/advisories/new

Include what you found, how to reproduce it, and the impact you'd expect.

## Supported versions

Fixes land on the latest tagged version; there's no backport policy.
