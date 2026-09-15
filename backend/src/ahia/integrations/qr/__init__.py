"""QR adapters.

A QR code is a transport mechanism, not an authorization mechanism: it carries the same public URL
a person would type, and it grants nothing that opening that URL in a browser would not.

Nothing here renders an image. The product builds the payload - the string a QR encoder turns into
a picture - and leaves the encoding to whichever client is printing it, because the web client
renders QR codes in the browser and the mobile client renders them on the device, and neither wants
a PNG from the API. The rule that matters is stated in `qr_payload`: only public, stable URLs go in,
and never internal identifiers or database state.
"""
