"""WhatsApp adapters.

The initial integration is Click-to-Chat: AHIA builds a ``wa.me`` link with a
contextual, pre-filled message, and the conversation continues inside WhatsApp
where it already happens.

Rules:

1. The service produces the intent - which product, which price, which URL,
   which optional inquiry text. The adapter produces the provider-specific
   link. Neither knows the other's format.
2. No WhatsApp Business API dependency. Sending a message is not treated as
   evidence of a sale.
3. Numbers are normalized to international format before a link is built, using
   the configured default country code.
4. Link content is URL-encoded properly; a product name containing an
   ampersand or a newline must not break the link.
"""
