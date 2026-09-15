"""Scheduled work.

A job is a use case with no caller: it runs on a timer, it has no request, no user and no tenant
context, and the only authorization it has is the deployment's own database credentials. That is
exactly why jobs live in their own package and are named after the schedule they keep rather than
after an entity - and why every job is a thin entry point over a service method, so the rule it
applies is the same rule the API applies.

Each module here is runnable with `python -m ahia.jobs.<name>`, prints an ASCII summary, and exits
non-zero when it could not do its work. A job that fails silently is a job nobody notices has
stopped
running until the thing it maintains is wrong.
"""
