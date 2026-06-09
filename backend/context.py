import contextvars

user_context = contextvars.ContextVar("username", default="-")
